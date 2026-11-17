"""Plain-text report for the terminal (colour optional)."""

from __future__ import annotations

import textwrap
from typing import List, Optional

from .collect import LEVEL_ERROR, LEVEL_INFO, LEVEL_WARNING
from .dates import format_datetime
from .model import POWER_DEALLOCATED, TYPE_VMSS
from .report import GenerationSummary, Report, TenantReport
from .textfmt import (
    Palette,
    clean_text,
    format_hourly,
    format_money,
    format_pct,
    plural,
    render_table,
)

NOT_AVAILABLE = "n/a"
_LEVEL_STYLES = {LEVEL_ERROR: ("ERROR", "bad"), LEVEL_WARNING: ("WARN", "warn"), LEVEL_INFO: ("NOTE", "dim")}

DEMO_BANNER = "DEMO: synthetic data generated locally. Nothing was read from Azure."
_MAX_CONSOLE_SKUS = 12
_MAX_CONSOLE_SUBS = 12
_MAX_CONSOLE_VMS = 15


def _wrap(text: str, width: Optional[int], initial: str, subsequent: str) -> List[str]:
    if width is None:
        return [initial + text]
    return textwrap.wrap(
        text, width=max(40, width), initial_indent=initial, subsequent_indent=subsequent,
        break_long_words=False, break_on_hyphens=False,
    ) or [initial]


def _gen_row(
    tenant_label: str,
    summary: GenerationSummary,
    currency: str,
    available: bool,
) -> List[str]:
    if not available:
        return [tenant_label, summary.generation] + [NOT_AVAILABLE] * 6
    return [
        tenant_label,
        summary.generation,
        str(summary.instance_count),
        str(summary.total_vcpus),
        format_money(summary.current_monthly, currency),
        format_money(summary.feb_monthly, currency),
        format_money(summary.monthly_delta, currency, signed=True),
        format_pct(summary.effective_hike_pct, signed=True),
    ]


def render_console(report: Report, *, width: Optional[int] = None, color: bool = False) -> str:
    palette = Palette(color)
    paint = palette.paint
    tz = report.tz
    cur = report.currency
    lines: List[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)

    if report.demo:
        emit(paint(DEMO_BANNER, "warn"))
        emit()

    emit(paint("Azure legacy VM SKU (v1, v2, v3) cost & February 2027 hike report", "head"))
    emit(f"Generated   {format_datetime(report.generated_at, tz)} ({report.tz_name})")
    emit(f"Hike model  {clean_text(report.policy.label)}")
    emit(f"Cost basis  {clean_text(report.cost_basis_description)}")
    names = ", ".join(clean_text(t.display_name) for t in report.tenants)
    emit(f"Tenants     {len(report.tenants)} ({names})")
    for note in report.notes:
        emit(paint(f"Note        {clean_text(note)}", "warn"))
    emit()

    emit(paint("Summary by generation (v1, v2, v3)", "head"))
    headers = [
        "Tenant",
        "Gen",
        "Instances",
        "vCPUs",
        "Current / mo",
        "Feb 2027 / mo",
        "Increase / mo",
        "Hike %",
    ]
    compact = [
        "Tenant",
        "Gen",
        "Inst",
        "vCPUs",
        "Current\n/ mo",
        "Feb 2027\n/ mo",
        "Increase\n/ mo",
        "Hike",
    ]
    rows: List[List[str]] = []
    styles: List[List[Optional[str]]] = []
    for tenant in report.tenants:
        ok = tenant.fetched
        for gen in report.generations:
            s = tenant.by_generation[gen]
            rows.append(_gen_row(tenant.display_name, s, cur, ok))
            styles.append([None, None, None, None, None, None, "warn" if ok and s.monthly_delta > 0 else None, None])
        tot = tenant.total_summary
        rows.append(_gen_row(tenant.display_name, tot, cur, ok))
        styles.append(["bold", "bold", "bold", "bold", "bold", "bold", "bad" if ok and tot.monthly_delta > 0 else "bold", "bold"])

    if len(report.tenants) > 1:
        any_ok = any(t.fetched for t in report.tenants)
        by_gen = report.totals_by_generation()
        for gen in report.generations:
            s = by_gen[gen]
            rows.append(_gen_row("All tenants", s, cur, any_ok))
            styles.append([None, None, None, None, None, None, "warn" if any_ok and s.monthly_delta > 0 else None, None])
        gt = report.grand_total()
        rows.append(_gen_row("All tenants", gt, cur, any_ok))
        styles.append(["bold", "bold", "bold", "bold", "bold", "bold", "bad" if any_ok and gt.monthly_delta > 0 else "bold", "bold"])

    aligns = ["l", "l", "r", "r", "r", "r", "r", "r"]
    for line in render_table(
        headers, rows, aligns=aligns, flexible=[True] + [False] * 7,
        styles=styles, width=width, palette=palette, compact_headers=compact,
    ):
        emit(line)

    gt = report.grand_total()
    if any(t.fetched for t in report.tenants):
        emit()
        emit(
            f"  1. Current cost today:             "
            f"{paint(format_money(gt.current_monthly, cur) + '/mo', 'bold')} "
            f"({format_money(gt.current_monthly * 12.0, cur)}/yr)"
        )
        emit(
            f"  2. Feb 2027 doing nothing:         "
            f"{paint(format_money(gt.feb_monthly, cur) + '/mo', 'warn')} "
            f"({paint(format_money(gt.monthly_delta, cur, signed=True) + '/mo, ' + format_pct(gt.effective_hike_pct, signed=True) + ' vs today', 'bad' if gt.monthly_delta > 0 else 'ok')} "
            f"| {format_money(gt.annual_delta, cur, signed=True)}/yr due to legacy SKU hikes)"
        )
        v5_ri_save = round(gt.feb_monthly - gt.target_v5_3yr_ri_monthly, 2)
        emit(
            f"  3. Feb 2027 migrating to v5 PAYG:  "
            f"{paint(format_money(gt.target_v5_monthly, cur) + '/mo', 'ok')} "
            f"({paint(format_money(gt.target_v5_delta_vs_current, cur, signed=True) + '/mo (' + format_pct(gt.target_v5_pct_vs_current, signed=True) + ') vs today', 'ok' if gt.target_v5_delta_vs_current <= 0 else 'warn')}; "
            f"{paint(format_money(gt.target_v5_delta_vs_feb, cur, signed=True) + '/mo (' + format_pct(gt.target_v5_pct_vs_feb, signed=True) + ') vs doing nothing', 'ok')})"
        )
        emit(
            f"  4. Feb 2027 migrating to v5 3Y RI: "
            f"{paint(format_money(gt.target_v5_3yr_ri_monthly, cur) + '/mo', 'ok')} "
            f"(saves {paint(format_money(v5_ri_save, cur) + '/mo', 'ok')} vs doing nothing in Feb 2027)"
        )
        if gt.deallocated_instances > 0 and not report.include_deallocated_cost:
            emit(
                paint(
                    f"  Deallocated fleet exposure ({gt.deallocated_instances} deallocated instance(s)): "
                    f"if started 24x7, total monthly cost rises from "
                    f"{format_money(gt.provisioned_current_monthly, cur)}/mo to "
                    f"{format_money(gt.provisioned_feb_monthly, cur)}/mo "
                    f"({format_money(gt.provisioned_monthly_delta, cur, signed=True)}/mo).",
                    "warn",
                )
            )

    missing = report.missing_tenants()
    if missing:
        emit()
        for line in _wrap(
            f"Totals exclude tenant(s) that could not be read: {', '.join(missing)}.",
            width, "  ", "  ",
        ):
            emit(paint(line, "warn"))

    for tenant in report.tenants:
        emit()
        _tenant_section(report, tenant, emit, palette, width)

    if report.demo:
        emit()
        emit(paint(DEMO_BANNER, "warn"))
    emit()
    emit(paint(f"azure-legacy-vm-report {report.version}", "dim"))
    return "\n".join(lines) + "\n"


def _tenant_section(
    report: Report, tenant: TenantReport, emit, palette: Palette, width: Optional[int]
) -> None:
    paint = palette.paint
    cur = report.currency
    extras = [clean_text(part) for part in (tenant.tenant_id, tenant.default_domain) if part]
    emit(paint(f"\u25a0 {clean_text(tenant.display_name)}", "head") + paint(f"  ({', '.join(extras)})", "dim"))

    context = []
    if tenant.data.subscription_count is not None:
        context.append(plural(tenant.data.subscription_count, "subscription") + " visible")
    if tenant.fetched:
        context.append(f"{tenant.data.total_resources_scanned} compute resource(s) scanned")
        context.append(f"{len(tenant.records)} legacy (v1-v3) deployment(s) found")
        if tenant.data.discovery_method:
            context.append(f"via {tenant.data.discovery_method}")
    if context:
        emit(paint("  " + " \u00b7 ".join(context), "dim"))

    if not tenant.fetched:
        emit(paint("  No VM inventory could be retrieved for this tenant.", "bad"))
    elif not tenant.records:
        emit(paint("  No legacy v1, v2 or v3 VM SKUs are deployed in this tenant.", "ok"))
    else:
        shown_skus = tenant.sku_rows[:_MAX_CONSOLE_SKUS]
        emit()
        sku_title = (
            f"  Top {len(shown_skus)} of {len(tenant.sku_rows)} legacy SKUs by hike impact"
            if len(tenant.sku_rows) > _MAX_CONSOLE_SKUS
            else "  By legacy SKU"
        )
        emit(paint(sku_title, "bold"))
        sku_headers = [
            "SKU",
            "Gen",
            "Inst",
            "Run/Off",
            "Current / mo",
            "Feb 2027 / mo",
            "Hike / mo",
            "Target SKU",
            "Plan / mo",
        ]
        sku_rows = [
            [
                row.sku,
                row.generation,
                str(row.instance_count),
                f"{row.running_instances}/{row.deallocated_instances}",
                format_money(row.current_monthly, cur),
                format_money(row.feb_monthly, cur),
                format_money(row.monthly_delta, cur, signed=True) if abs(row.monthly_delta) > 0.005 else "\u2014",
                row.target_v5_sku or row.recommended_v5,
                format_money(row.target_v5_monthly, cur),
            ]
            for row in shown_skus
        ]
        sku_styles = [
            [
                "bold",
                "bad" if row.generation in ("v1", "v2") else "warn",
                None,
                None,
                None,
                None,
                "bad" if row.monthly_delta > 0.005 else "dim",
                "dim",
                "ok",
            ]
            for row in shown_skus
        ]
        for line in render_table(
            sku_headers,
            sku_rows,
            aligns=["l", "l", "r", "r", "r", "r", "r", "l", "r"],
            flexible=[False, False, False, False, False, False, False, True, False],
            styles=sku_styles,
            width=width,
            palette=palette,
        ):
            emit(line)
        if len(tenant.sku_rows) > _MAX_CONSOLE_SKUS:
            emit(paint(f"  \u2026 plus {len(tenant.sku_rows) - _MAX_CONSOLE_SKUS} more SKU(s) in CSV/HTML report.", "dim"))

        if tenant.management_group_rows:
            emit()
            emit(paint("  By management group", "bold"))
            mg_headers = [
                "Management group",
                "Subs",
                "Total Inst",
                "vCPUs",
                "Current / mo",
                "Feb 2027 / mo",
                "Hike / mo",
                "Target v5 / mo",
                "Save vs Feb / mo",
            ]
            mg_rows = [
                [
                    row.management_group,
                    str(row.subscription_count),
                    str(row.total_instances),
                    str(row.total_vcpus),
                    format_money(row.current_monthly, cur),
                    format_money(row.feb_monthly, cur),
                    format_money(row.monthly_delta, cur, signed=True) if abs(row.monthly_delta) > 0.005 else "\u2014",
                    format_money(row.target_v5_monthly, cur),
                    format_money(row.target_v5_savings_vs_feb, cur, signed=True)
                    if abs(row.target_v5_savings_vs_feb) > 0.005
                    else "\u2014",
                ]
                for row in tenant.management_group_rows
            ]
            for line in render_table(
                mg_headers,
                mg_rows,
                aligns=["l", "r", "r", "r", "r", "r", "r", "r", "r"],
                flexible=[True] + [False] * 8,
                width=width,
                palette=palette,
            ):
                emit(line)

        shown_subs = tenant.subscription_rows[:_MAX_CONSOLE_SUBS]
        emit()
        sub_title = (
            f"  Top {len(shown_subs)} of {len(tenant.subscription_rows)} subscriptions by hike impact"
            if len(tenant.subscription_rows) > _MAX_CONSOLE_SUBS
            else "  By subscription"
        )
        emit(paint(sub_title, "bold"))
        sub_headers = [
            "Subscription",
            "v1",
            "v2",
            "v3",
            "Total Inst",
            "vCPUs",
            "Current / mo",
            "Feb 2027 / mo",
            "Hike / mo",
            "Plan / mo",
        ]
        sub_rows = [
            [
                row.subscription_name,
                str(row.v1_instances),
                str(row.v2_instances),
                str(row.v3_instances),
                str(row.total_instances),
                str(row.total_vcpus),
                format_money(row.current_monthly, cur),
                format_money(row.feb_monthly, cur),
                format_money(row.monthly_delta, cur, signed=True) if abs(row.monthly_delta) > 0.005 else "\u2014",
                format_money(row.target_v5_monthly, cur),
            ]
            for row in shown_subs
        ]
        for line in render_table(
            sub_headers,
            sub_rows,
            aligns=["l", "r", "r", "r", "r", "r", "r", "r", "r", "r"],
            flexible=[True] + [False] * 9,
            width=width,
            palette=palette,
        ):
            emit(line)
        if len(tenant.subscription_rows) > _MAX_CONSOLE_SUBS:
            rem_subs = len(tenant.subscription_rows) - _MAX_CONSOLE_SUBS
            emit(paint(f"  \u2026 plus {rem_subs} lower-impact subscription(s) in CSV/HTML report.", "dim"))

        shown_vms = tenant.records[:_MAX_CONSOLE_VMS]
        emit()
        vm_title = (
            f"  Top {len(shown_vms)} of {len(tenant.records)} legacy deployments by hike impact"
            if len(tenant.records) > _MAX_CONSOLE_VMS
            else f"  Deployed legacy resources ({len(tenant.records)})"
        )
        emit(paint(vm_title, "bold"))
        vm_headers = [
            "Name",
            "Subscription",
            "SKU",
            "Gen",
            "State",
            "Current / mo",
            "Feb 2027 / mo",
            "Hike / mo",
            "Target SKU",
        ]
        vm_rows = []
        vm_styles = []
        for rec in shown_vms:
            name_label = f"{rec.name} (VMSS x{rec.instance_count})" if rec.resource_type == TYPE_VMSS else rec.name
            vm_rows.append([
                name_label,
                rec.subscription_name,
                rec.sku,
                rec.generation,
                rec.power_state,
                format_money(rec.current_monthly, cur),
                format_money(rec.feb_monthly, cur),
                format_money(rec.monthly_delta, cur, signed=True) if abs(rec.monthly_delta) > 0.005 else "\u2014",
                rec.target_v5_sku or rec.recommended_v5,
            ])
            state_style = "dim" if rec.power_state == POWER_DEALLOCATED else "ok"
            vm_styles.append([
                None,
                None,
                None,
                "bad" if rec.generation in ("v1", "v2") else "warn",
                state_style,
                None,
                None,
                "bad" if rec.monthly_delta > 0.005 else "dim",
                "dim",
            ])
        for line in render_table(
            vm_headers,
            vm_rows,
            aligns=["l", "l", "l", "l", "l", "r", "r", "r", "l"],
            flexible=[True, True, False, False, False, False, False, False, False],
            styles=vm_styles,
            width=width,
            palette=palette,
        ):
            emit(line)
        if len(tenant.records) > _MAX_CONSOLE_VMS:
            rem_vms = len(tenant.records) - _MAX_CONSOLE_VMS
            emit(paint(
                f"  \u2026 plus {rem_vms} more deployment(s) \u2014 open HTML or CSV output for the full inventory.",
                "dim",
            ))

    if tenant.issues:
        emit()
        for issue in tenant.issues:
            tag, style = _LEVEL_STYLES.get(issue.level, ("NOTE", "dim"))
            text = f"[{issue.feature}] {clean_text(issue.message)}"
            for line in _wrap(f"{tag:5} {text}", width, "  ", "        "):
                emit(paint(line, style))
