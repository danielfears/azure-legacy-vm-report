"""Command-line interface: select tenants, inventory v1/v2/v3 VMs, model February 2027 hikes and render reports."""

from __future__ import annotations

import argparse
import contextlib
import logging
import math
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, TextIO, Tuple

from . import __version__
from .auth import (
    LOGIN_HINT,
    AuthError,
    AzCli,
    AzCliTokenProvider,
    RoutingTokenProvider,
    ServicePrincipalTokenProvider,
    SpCredential,
    TokenProvider,
)
from .collect import (
    LEVEL_ERROR,
    CollectOptions,
    TenantData,
    collect_tenant,
    merge_repeats,
)
from .config import (
    AUTH_SP,
    CLOUDS,
    DEFAULT_CLOUD,
    Cloud,
    ConfigError,
    LoadedConfig,
    TenantSpec,
    current_az_tenant,
    discover_az_tenants,
    load_config,
    parse_subscription_filter,
    parse_tenant_args,
)
from .console import render_console
from .dates import UTC, parse_instant, resolve_timezone
from .demo import DemoTokens, DemoTransport, build_demo_specs
from .model import COST_SOURCE_AUTO, VALID_COST_SOURCES
from .outputs import (
    FORMAT_CONSOLE,
    FORMAT_HTML,
    default_stem,
    inside_git_repository,
    open_in_browser,
    parse_formats,
    prepare_directory,
    render_files,
    write_files,
)
from .pricing import (
    DEFAULT_CURRENCY,
    DEFAULT_HOURS_PER_MONTH,
    POLICY_CUSTOM,
    POLICY_LEGACY_25,
    POLICY_SERVICE_HEALTH,
    VALID_POLICIES,
    HikePolicy,
    PricingClient,
)
from .report import Report, build_report
from .skus import LEGACY_GENERATIONS
from .textfmt import clean_text, plural
from .transport import Transport, UrllibTransport

PROG = "azure-legacy-vm-report"
DEFAULT_TZ = "Europe/London"
DEFAULT_OUT_DIR = "azure-legacy-vm-reports"
LOGGER_NAME = "azure_legacy_vm_report"
SUPPORTED_CURRENCIES = ("GBP", "USD", "EUR")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_PARTIAL = 3
EXIT_BROKEN_PIPE = 141
EXIT_INTERRUPTED = 130

DESCRIPTION = """\
Inventory every deployed v1, v2 and v3 Azure Virtual Machine (and Virtual Machine Scale Set)
across one or more tenants, calculate their current monthly cost, and project their monthly
and annual cost in February 2027 after the announced Azure price hikes. Read-only: changes
nothing in Azure.
"""

EPILOG = f"""\
examples:
  {PROG}                                        current Azure CLI tenant, console report
  {PROG} --format console,html,csv --open       console + CSV + interactive HTML report
  {PROG} --all-tenants --format console,html --open
  {PROG} --tenant <tenant-id> --hike-model service-health
  {PROG} --v1-hike 25 --v2-hike 25 --v3-hike 25 --currency GBP
  {PROG} --demo --format console,html --open    synthetic data, no Azure login needed

exit status:
  0 success   1 failed (nothing could be analysed)   2 usage error
  3 partial (some tenants had errors)                130 interrupted
"""

_API_VERSION = re.compile(r"^\d{4}-\d{2}-\d{2}(-preview)?$")


class CliError(Exception):
    status = EXIT_FAILED


class UsageError(CliError):
    status = EXIT_USAGE


def parse_generations(values: Sequence[str]) -> Tuple[str, ...]:
    if not values:
        return LEGACY_GENERATIONS
    chosen = []
    seen = set()
    for val in values:
        for part in str(val).split(","):
            g = part.strip().lower()
            if not g:
                continue
            if not g.startswith("v"):
                g = "v" + g
            if g not in LEGACY_GENERATIONS:
                raise UsageError(f"Unknown VM generation {part.strip()!r}. Choose from v1, v2, v3.")
            if g not in seen:
                seen.add(g)
                chosen.append(g)
    if not chosen:
        raise UsageError("No VM generation was selected.")
    return tuple(g for g in LEGACY_GENERATIONS if g in seen)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scope = parser.add_argument_group("tenant & subscription scope")
    scope.add_argument(
        "--tenant", "-t", action="append", default=[], metavar="ID[,ID]",
        help="Tenant GUID or domain name to scan (repeat or comma-separate; default: current 'az' tenant).",
    )
    scope.add_argument(
        "--all-tenants", action="store_true",
        help="Scan every tenant known to 'az account list --all' (plus any in --config).",
    )
    scope.add_argument(
        "--subscription", "-s", action="append", default=[], metavar="GUID[,GUID]",
        help="Restrict the scan to specific subscription GUID(s).",
    )
    scope.add_argument(
        "--config", type=Path, metavar="FILE",
        help="JSON file listing tenants and optional service-principal credentials.",
    )
    scope.add_argument(
        "--cloud", choices=tuple(CLOUDS), default=None,
        help=f"Azure cloud environment (default: {DEFAULT_CLOUD}).",
    )

    model = parser.add_argument_group("SKU & February 2027 price-hike model")
    model.add_argument(
        "--generation", "-g", action="append", default=[], metavar="GEN[,GEN]",
        help="Legacy VM generations to include: v1, v2, v3 (default: v1,v2,v3).",
    )
    model.add_argument(
        "--hike-model", choices=VALID_POLICIES, default=POLICY_SERVICE_HEALTH,
        help=(
            "February 2027 price-hike rule: 'service-health' (default) applies +25%% globally to "
            "End-of-Life v1/v2 series and the regional +8-17%% hike to non-excluded v2/v3 series in "
            "the 7 affected regions (0%% in UK regions); 'legacy-25' applies a blanket +25%% across "
            "all v1, v2 and v3; 'custom' uses --v1-hike/--v2-hike/--v3-hike."
        ),
    )
    model.add_argument(
        "--v1-hike", type=float, default=None, metavar="PCT",
        help="Percentage price increase for v1 SKUs in February 2027 (default: 25).",
    )
    model.add_argument(
        "--v2-hike", type=float, default=None, metavar="PCT",
        help="Percentage price increase for v2 SKUs in February 2027 (default: 25).",
    )
    model.add_argument(
        "--v3-hike", type=float, default=None, metavar="PCT",
        help="Percentage price increase for v3 SKUs in February 2027 (default: 25 for legacy-25, 0 for service-health).",
    )
    model.add_argument(
        "--cost-source", choices=VALID_COST_SOURCES, default=COST_SOURCE_AUTO,
        help=(
            "Baseline monthly cost source: 'auto' (default) uses last month's actual billed Cost Management "
            "spend (with current MTD extrapolation for new VMs and Retail API fallback if Cost Management "
            "is unavailable); 'last-month' uses last month's actual cost; 'mtd' uses current month-to-date "
            "extrapolated cost; 'retail' uses the 730h/mo Azure Retail Prices API rate."
        ),
    )
    model.add_argument(
        "--currency", default=DEFAULT_CURRENCY, metavar="CODE",
        help=f"Billing currency code for Retail Prices lookup (default: {DEFAULT_CURRENCY}; e.g. GBP, USD, EUR).",
    )
    model.add_argument(
        "--hours-per-month", type=float, default=DEFAULT_HOURS_PER_MONTH, metavar="HOURS",
        help=f"Hours per month for monthly cost calculation (default: {DEFAULT_HOURS_PER_MONTH:g}).",
    )
    model.add_argument(
        "--include-deallocated-cost", action="store_true",
        help="Include deallocated VMs in active monthly cost totals (as if running 24x7).",
    )
    model.add_argument(
        "--no-vmss", action="store_true",
        help="Exclude Virtual Machine Scale Sets and scan standalone Virtual Machines only.",
    )
    model.add_argument(
        "--no-arg", action="store_true",
        help="Skip Azure Resource Graph and query the per-subscription ARM Compute API directly.",
    )
    model.add_argument(
        "--offline-prices", action="store_true",
        help="Use the built-in retail rate table without querying https://prices.azure.com.",
    )

    out = parser.add_argument_group("output options")
    out.add_argument(
        "--format", "-f", action="append", default=[], metavar="FMT[,FMT]",
        help="Output format(s): console (default), csv, json, md, html, or all.",
    )
    out.add_argument(
        "--out-dir", "-o", type=Path, default=None, metavar="DIR",
        help=f"Directory for file outputs (default: ~/{DEFAULT_OUT_DIR}).",
    )
    out.add_argument(
        "--open", action="store_true",
        help="Open the generated HTML report in your default browser.",
    )
    out.add_argument(
        "--tz", default=DEFAULT_TZ, metavar="ZONE",
        help=f"Time zone for displayed dates (default: {DEFAULT_TZ}).",
    )
    out.add_argument(
        "--as-of", default=None, metavar="TIMESTAMP",
        help="Override the report generation timestamp (ISO 8601).",
    )
    out.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI colour in console output.",
    )

    net = parser.add_argument_group("execution & network")
    net.add_argument("--jobs", "-j", type=int, default=4, metavar="N", help="Parallel tenant workers (default: 4).")
    net.add_argument("--http-timeout", type=float, default=60.0, metavar="SEC", help="ARM HTTP timeout in seconds.")
    net.add_argument("--az-timeout", type=float, default=90.0, metavar="SEC", help="Azure CLI timeout in seconds.")
    net.add_argument("--max-retries", type=int, default=4, metavar="N", help="Retries on HTTP 429/5xx (default: 4).")
    net.add_argument("--resource-graph-api-version", default="2022-10-01", metavar="VER")
    net.add_argument("--compute-api-version", default="2024-07-01", metavar="VER")
    net.add_argument("--cost-management-api-version", default="2023-11-01", metavar="VER")
    net.add_argument("--demo", action="store_true", help="Run on synthetic data with no Azure login required.")
    net.add_argument("-q", "--quiet", action="store_true", help="Suppress progress messages on stderr.")
    net.add_argument("-v", "--verbose", action="store_true", help="Log HTTP requests and detailed errors to stderr.")
    net.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    return parser


def _resolve_hike_policy(args: argparse.Namespace) -> HikePolicy:
    custom_given = any(x is not None for x in (args.v1_hike, args.v2_hike, args.v3_hike))
    mode = args.hike_model
    if custom_given:
        mode = POLICY_CUSTOM

    v1 = 25.0 if args.v1_hike is None else float(args.v1_hike)
    v2 = 25.0 if args.v2_hike is None else float(args.v2_hike)
    default_v3 = 0.0 if mode == POLICY_SERVICE_HEALTH else 25.0
    v3 = default_v3 if args.v3_hike is None else float(args.v3_hike)

    for label, val in (("--v1-hike", v1), ("--v2-hike", v2), ("--v3-hike", v3)):
        if not math.isfinite(val) or val < -100.0 or val > 1000.0:
            raise UsageError(f"{label} must be between -100 and 1000.")
    return HikePolicy(
        name=mode,
        v1_hike_pct=v1,
        v2_hike_pct=v2,
        v3_hike_pct=v3,
        apply_regional_to_v3=(mode == POLICY_SERVICE_HEALTH),
    )


def _validate_args(args: argparse.Namespace) -> Tuple[List[str], Tuple[str, ...], List[str], HikePolicy]:
    try:
        formats = parse_formats(args.format or [FORMAT_CONSOLE])
    except ValueError as exc:
        raise UsageError(str(exc)) from None

    if args.open and FORMAT_HTML not in formats:
        formats.append(FORMAT_HTML)

    generations = parse_generations(args.generation)
    try:
        sub_filter = parse_subscription_filter(args.subscription)
    except ConfigError as exc:
        raise UsageError(str(exc)) from None

    if not math.isfinite(args.hours_per_month) or args.hours_per_month <= 0 or args.hours_per_month > 8784:
        raise UsageError("--hours-per-month must be between 1 and 8784.")
    if args.jobs < 1 or args.jobs > 32:
        raise UsageError("--jobs must be between 1 and 32.")
    if not math.isfinite(args.http_timeout) or args.http_timeout <= 0:
        raise UsageError("--http-timeout must be greater than 0.")
    if not math.isfinite(args.az_timeout) or args.az_timeout <= 0:
        raise UsageError("--az-timeout must be greater than 0.")
    if args.max_retries < 0 or args.max_retries > 20:
        raise UsageError("--max-retries must be between 0 and 20.")
    for flag, ver in (
        ("--resource-graph-api-version", args.resource_graph_api_version),
        ("--compute-api-version", args.compute_api_version),
        ("--cost-management-api-version", args.cost_management_api_version),
    ):
        if not _API_VERSION.match(ver or ""):
            raise UsageError(f"{flag} must look like YYYY-MM-DD (or YYYY-MM-DD-preview).")

    currency = (args.currency or DEFAULT_CURRENCY).strip().upper()
    if not re.match(r"^[A-Z]{3}$", currency):
        raise UsageError(f"Invalid currency code {args.currency!r}. Use a 3-letter ISO code such as GBP, USD or EUR.")

    policy = _resolve_hike_policy(args)
    return formats, generations, sub_filter, policy


def _select_tenants(
    args: argparse.Namespace,
    loaded: Optional[LoadedConfig],
    az: AzCli,
) -> Tuple[List[TenantSpec], List[str]]:
    notes: List[str] = []
    try:
        cli_specs = parse_tenant_args(args.tenant)
    except ConfigError as exc:
        raise UsageError(str(exc)) from None

    cfg_by_id: Dict[str, TenantSpec] = {
        spec.tenant_id.lower(): spec for spec in (loaded.tenants if loaded else ())
    }

    if cli_specs:
        merged: List[TenantSpec] = []
        for spec in cli_specs:
            key = spec.tenant_id.lower()
            merged.append(cfg_by_id.get(key, spec))
        return merged, notes

    if args.all_tenants:
        specs: List[TenantSpec] = list(loaded.tenants if loaded else ())
        seen = {s.tenant_id.lower() for s in specs}
        try:
            for spec in discover_az_tenants(az):
                if spec.tenant_id.lower() not in seen:
                    seen.add(spec.tenant_id.lower())
                    specs.append(spec)
        except AuthError as exc:
            if not specs:
                raise CliError(str(exc)) from None
            notes.append(f"Could not list additional Azure CLI tenants: {exc}")
        if not specs:
            raise CliError(f"No tenants were found. {LOGIN_HINT}")
        return specs, notes

    if loaded and loaded.tenants:
        return list(loaded.tenants), notes

    try:
        return [current_az_tenant(az)], notes
    except AuthError as exc:
        raise CliError(str(exc)) from None


def _build_token_provider(
    specs: Sequence[TenantSpec],
    cloud: Cloud,
    az: AzCli,
    transport: Transport,
    env: Mapping[str, str],
) -> TokenProvider:
    hints = {s.tenant_id.lower(): s.subscription_hint for s in specs if s.subscription_hint}
    az_provider = AzCliTokenProvider(az, cloud.arm_resource, hints=hints)
    sp_creds = {
        s.tenant_id.lower(): SpCredential(client_id=s.client_id, secret_env=s.secret_env)
        for s in specs
        if s.auth == AUTH_SP
    }
    if not sp_creds:
        return az_provider
    sp_provider = ServicePrincipalTokenProvider(
        sp_creds, transport, authority_host=cloud.authority, scope=cloud.arm_scope, env=env
    )
    overrides = {tid: sp_provider for tid in sp_creds}
    return RoutingTokenProvider(az_provider, overrides)


def run_cli(
    argv: Optional[Sequence[str]] = None,
    *,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    env: Optional[Mapping[str, str]] = None,
    transport: Optional[Transport] = None,
    az_cli: Optional[AzCli] = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    environ = os.environ if env is None else env

    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE

    _configure_logging(err, verbose=args.verbose)
    az: Optional[AzCli] = az_cli
    try:
        formats, generations, sub_filter, policy = _validate_args(args)
        tz, tz_warning = resolve_timezone(args.tz)
        notes: List[str] = [tz_warning] if tz_warning else []

        if args.as_of:
            generated_at = parse_instant(args.as_of, default_tz=tz)
            if generated_at is None:
                raise UsageError(f"Could not parse --as-of timestamp {args.as_of!r}. Use YYYY-MM-DD or ISO 8601.")
        else:
            generated_at = now_fn()

        loaded: Optional[LoadedConfig] = None
        if args.config is not None:
            if args.demo:
                raise UsageError("--config cannot be combined with --demo.")
            try:
                loaded = load_config(args.config)
            except ConfigError as exc:
                raise UsageError(str(exc)) from None

        cloud_name = args.cloud or (loaded.cloud if loaded and loaded.cloud else DEFAULT_CLOUD)
        cloud = CLOUDS[cloud_name]
        currency = (args.currency or DEFAULT_CURRENCY).strip().upper()

        if args.demo:
            if args.tenant or args.all_tenants:
                raise UsageError("--demo cannot be combined with --tenant or --all-tenants.")
            specs = build_demo_specs()
            active_transport: Transport = DemoTransport()
            tokens: TokenProvider = DemoTokens()
            offline_prices = True
        else:
            active_transport = transport or UrllibTransport()
            az = az or AzCli(timeout=args.az_timeout, env=environ)
            specs, discovery_notes = _select_tenants(args, loaded, az)
            notes.extend(discovery_notes)
            tokens = _build_token_provider(specs, cloud, az, active_transport, environ)
            offline_prices = bool(args.offline_prices)

        pricing = PricingClient(
            active_transport,
            currency=currency,
            endpoint=cloud.prices_api,
            offline=offline_prices,
            timeout=min(args.http_timeout, 25.0),
        )
        collect_opts = CollectOptions(
            generations=generations,
            subscription_filter=tuple(sub_filter),
            include_vmss=not args.no_vmss,
            include_deallocated_cost=args.include_deallocated_cost,
            hours_per_month=args.hours_per_month,
            cost_source=args.cost_source,
            as_of=generated_at,
            use_resource_graph=not args.no_arg,
            resource_graph_api=args.resource_graph_api_version,
            compute_api=args.compute_api_version,
            cost_management_api=args.cost_management_api_version,
            timeout=args.http_timeout,
            max_retries=args.max_retries,
        )

        if not args.quiet:
            _progress(err, f"Scanning {plural(len(specs), 'tenant')} for legacy ({', '.join(generations)}) VMs\u2026")

        raw_results = _collect_all(specs, tokens, active_transport, cloud.arm, pricing, policy, collect_opts, args.jobs)
        merged_results, dropped = merge_repeats(raw_results)
        if dropped:
            notes.append("Duplicate tenant entries resolved to the same tenant GUID and were merged.")

        report = build_report(
            merged_results,
            version=__version__,
            generated_at=generated_at,
            tz=tz,
            tz_name=args.tz if not tz_warning else "UTC",
            currency=currency,
            hours_per_month=args.hours_per_month,
            policy=policy,
            generations=generations,
            include_vmss=not args.no_vmss,
            include_deallocated_cost=args.include_deallocated_cost,
            cost_source=args.cost_source,
            notes=notes,
            demo=args.demo,
        )

        return _emit_outputs(args, report, formats, out, err, environ)

    except UsageError as exc:
        _write_err(err, f"{PROG}: {clean_text(exc)}")
        return EXIT_USAGE
    except CliError as exc:
        _write_err(err, f"{PROG}: {clean_text(exc)}")
        return exc.status
    except BrokenPipeError:
        with contextlib.suppress(Exception):
            out.close()
        return EXIT_BROKEN_PIPE
    except KeyboardInterrupt:
        if az is not None:
            az.abort()
        _write_err(err, f"\n{PROG}: interrupted.")
        return EXIT_INTERRUPTED


def _collect_all(
    specs: Sequence[TenantSpec],
    tokens: TokenProvider,
    transport: Transport,
    endpoint: str,
    pricing: PricingClient,
    policy: HikePolicy,
    options: CollectOptions,
    jobs: int,
) -> List[TenantData]:
    def one(spec: TenantSpec) -> TenantData:
        return collect_tenant(
            spec,
            tokens=tokens,
            transport=transport,
            endpoint=endpoint,
            pricing=pricing,
            policy=policy,
            options=options,
        )

    if len(specs) <= 1 or jobs <= 1:
        return [one(spec) for spec in specs]
    with ThreadPoolExecutor(max_workers=min(jobs, len(specs))) as pool:
        return list(pool.map(one, specs))


def _emit_outputs(
    args: argparse.Namespace,
    report: Report,
    formats: Sequence[str],
    out: TextIO,
    err: TextIO,
    environ: Mapping[str, str],
) -> int:
    file_outputs = render_files(report, formats)
    written: List[Path] = []
    if file_outputs:
        target_dir = args.out_dir if args.out_dir is not None else (Path.home() / DEFAULT_OUT_DIR)
        try:
            prepare_directory(target_dir)
            if inside_git_repository(target_dir):
                _progress(
                    err,
                    f"Warning: writing report files inside a Git working tree ({target_dir}). "
                    "Reports contain tenant and subscription names/IDs; do not commit them.",
                )
            written = write_files(target_dir, default_stem(report), file_outputs)
        except OSError as exc:
            raise CliError(f"Could not write report files to {target_dir}: {exc}") from None

    if FORMAT_CONSOLE in formats:
        tty = hasattr(out, "isatty") and out.isatty()
        use_color = tty and not args.no_color and not environ.get("NO_COLOR")
        term_width: Optional[int] = None
        if tty:
            term_width = shutil.get_terminal_size((120, 24)).columns
        text = render_console(report, width=term_width, color=use_color)
        try:
            out.write(text)
            out.flush()
        except BrokenPipeError:
            raise

    if written and not args.quiet:
        for path in written:
            _progress(err, f"Wrote {path}")

    html_files = [path for path in written if path.suffix.lower() == ".html"]
    should_open = args.open or (bool(html_files) and hasattr(out, "isatty") and out.isatty())
    if html_files and should_open:
        warn = open_in_browser(html_files[0], env=environ)
        if warn and not args.quiet:
            _progress(err, warn)

    if all(t.fatal for t in report.tenants):
        return EXIT_FAILED
    if any(t.fatal or any(i.level == LEVEL_ERROR for i in t.issues) for t in report.tenants):
        return EXIT_PARTIAL
    return EXIT_OK


def _configure_logging(err: TextIO, *, verbose: bool) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.propagate = False
    if verbose:
        handler = logging.StreamHandler(err)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    else:
        logger.addHandler(logging.NullHandler())


def _progress(err: TextIO, message: str) -> None:
    with contextlib.suppress(BrokenPipeError, OSError):
        err.write(f"{clean_text(message)}\n")
        err.flush()


def _write_err(err: TextIO, message: str) -> None:
    with contextlib.suppress(BrokenPipeError, OSError):
        err.write(f"{message}\n")
        err.flush()
