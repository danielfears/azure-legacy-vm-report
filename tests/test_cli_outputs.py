"""End-to-end CLI, output format, security sanitisation and CSP verification tests."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from azure_legacy_vm_report.cli import EXIT_OK, EXIT_USAGE, run_cli
from azure_legacy_vm_report.csvout import safe_cell
from azure_legacy_vm_report.htmlout import SCRIPT, STYLE, content_security_policy, csp_hash


class CliAndOutputsTests(unittest.TestCase):
    def test_demo_all_formats_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "reports"
            stdout = io.StringIO()
            stderr = io.StringIO()
            rc = run_cli(
                [
                    "--demo",
                    "--format",
                    "all",
                    "--out-dir",
                    str(out_dir),
                    "--as-of",
                    "2026-10-28T16:15:00Z",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(rc, EXIT_OK, stderr.getvalue())
            console_text = stdout.getvalue()
            self.assertIn("Summary by generation (v1, v2, v3)", console_text)
            self.assertIn("Standard_D4_v2", console_text)
            self.assertIn("Standard_D8s_v3", console_text)
            self.assertIn("Standard_B2s", console_text)

            files = sorted(p.name for p in out_dir.iterdir())
            self.assertEqual(len(files), 7)  # 4 CSVs + JSON + MD + HTML

            json_file = next(out_dir.glob("*.json"))
            payload = json.loads(json_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["tool"], "azure-legacy-vm-report")
            self.assertEqual(payload["hike_policy"]["effective_date"], "2027-02-01")
            self.assertGreater(payload["totals"]["overall"]["current_monthly"], 0)
            self.assertGreater(payload["totals"]["overall"]["feb_monthly"], payload["totals"]["overall"]["current_monthly"])

            html_file = next(out_dir.glob("*.html"))
            html_text = html_file.read_text(encoding="utf-8")
            self.assertIn(csp_hash(STYLE), html_text)
            self.assertIn(csp_hash(SCRIPT), html_text)
            self.assertIn('id="hike-simulator"', html_text)
            self.assertFalse(any(ord(ch) < 32 and ch not in "\r\n\t" for ch in html_text))

    def test_service_health_hike_model_cli(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = run_cli(
            ["--demo", "--hike-model", "service-health", "--format", "console", "--quiet"],
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("Service Health notices", stdout.getvalue())

    def test_default_html_output_and_additive_format_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            default_dir = Path(tmp) / "default"
            rc1 = run_cli(
                ["--demo", "--out-dir", str(default_dir), "--no-open", "--quiet"],
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
            self.assertEqual(rc1, EXIT_OK)
            self.assertEqual([p.suffix for p in default_dir.iterdir()], [".html"])

            extra_dir = Path(tmp) / "extra"
            stdout2 = io.StringIO()
            rc2 = run_cli(
                ["--demo", "--csv", "--json", "--console", "--out-dir", str(extra_dir), "--no-open", "--quiet"],
                stdout=stdout2,
                stderr=io.StringIO(),
            )
            self.assertEqual(rc2, EXIT_OK)
            suffixes = sorted(p.suffix for p in extra_dir.iterdir())
            self.assertEqual(suffixes, [".csv", ".csv", ".csv", ".csv", ".html", ".json"])
            self.assertIn("Summary by generation", stdout2.getvalue())

    def test_service_health_with_v3_hike_preserves_regional_rules_and_html_features(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "sh"
            stdout = io.StringIO()
            stderr = io.StringIO()
            rc = run_cli(
                [
                    "--demo",
                    "--hike-model",
                    "service-health",
                    "--v3-hike",
                    "10",
                    "--include-regional-skus",
                    "--format",
                    "json,html,md,console",
                    "--out-dir",
                    str(out_dir),
                    "--quiet",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(rc, EXIT_OK, stderr.getvalue())
            payload = json.loads(next(out_dir.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(payload["hike_policy"]["name"], "service-health")
            self.assertEqual(payload["hike_policy"]["v3_hike_pct"], 10.0)
            # Dublin (northeurope) D4s_v3 still gets +17% regional hike, while UK South D8s_v3 gets +10%
            alpha_vms = {v["name"]: v for v in payload["tenants"][0]["vms"]}
            self.assertAlmostEqual(alpha_vms["vm-dublin-relay-01"]["hike_pct"], 17.0, places=1)
            self.assertAlmostEqual(alpha_vms["aks-systempool-vmss"]["hike_pct"], 10.0, places=1)

            html_text = next(out_dir.glob("*.html")).read_text(encoding="utf-8")
            self.assertIn('class="mg-summary-row"', html_text)
            self.assertIn('data-v5-ri-24x7="', html_text)
            self.assertIn('id="sim-mig-v5"', html_text)
            self.assertIn('<option value="v5">v5 only</option>', html_text)

            md_text = next(out_dir.glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("### Management group breakdown", md_text)
            self.assertIn("By management group", stdout.getvalue())

    def test_executive_brief_adapts_across_currency_zero_hike_and_single_sub(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "usd"
            stdout = io.StringIO()
            stderr = io.StringIO()
            rc = run_cli(
                [
                    "--demo",
                    "--currency",
                    "USD",
                    "--v1-hike",
                    "0",
                    "--v2-hike",
                    "0",
                    "--v3-hike",
                    "0",
                    "--format",
                    "html",
                    "--out-dir",
                    str(out_dir),
                    "--quiet",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(rc, EXIT_OK, stderr.getvalue())
            html_text = next(out_dir.glob("*.html")).read_text(encoding="utf-8")
            self.assertIn("0 hiked ($0)", html_text)
            self.assertIn("Spend Concentration", html_text)
            self.assertIn("Hiked (&gt;$0) only", html_text)
            self.assertNotIn("\u00a30", html_text)
            self.assertNotIn("UK v3", html_text)

    def test_invalid_arguments_return_usage_exit_code(self) -> None:
        for bad_args in (
            ["--demo", "--tenant", "11111111-1111-4111-8111-111111111111"],
            ["--generation", "v5"],
            ["--currency", "INVALID"],
            ["--hours-per-month", "0"],
        ):
            with self.subTest(args=bad_args):
                stdout = io.StringIO()
                stderr = io.StringIO()
                rc = run_cli(bad_args, stdout=stdout, stderr=stderr)
                self.assertEqual(rc, EXIT_USAGE)

    def test_csv_formula_injection_and_csp(self) -> None:
        self.assertEqual(safe_cell("=cmd|' /C calc'!A0"), "'=cmd|' /C calc'!A0")
        self.assertEqual(safe_cell("+SUM(A1:A2)"), "'+SUM(A1:A2)")
        self.assertEqual(safe_cell("-10"), "'-10")
        self.assertEqual(safe_cell("@malicious"), "'@malicious")
        self.assertEqual(safe_cell(25.5), 25.5)
        csp = content_security_policy()
        self.assertIn("default-src 'none'", csp)
        self.assertIn(csp_hash(STYLE), csp)
        self.assertIn(csp_hash(SCRIPT), csp)

    def test_update_check_banner_caching_fail_open_and_url_sanitisation(self) -> None:
        from datetime import datetime
        from azure_legacy_vm_report.dates import UTC
        from azure_legacy_vm_report.htmlout import render_html
        from azure_legacy_vm_report.pricing import HikePolicy
        from azure_legacy_vm_report.report import build_report
        from azure_legacy_vm_report.transport import Response, Transport, TransportError
        from azure_legacy_vm_report.update_check import (
            REPO_URL,
            check_for_update,
            is_update_check_disabled,
        )

        class FakeGhTransport(Transport):
            def __init__(self, status=200, payload=None, fail=False):
                self.status = status
                self.payload = payload or {}
                self.fail = fail
                self.calls = 0

            def request(self, method, url, headers, body, timeout):
                self.calls += 1
                if self.fail:
                    raise TransportError("blocked by firewall")
                return Response(self.status, {}, json.dumps(self.payload).encode("utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "update-check.json"
            # Untrusted html_url is rewritten safely to the canonical GitHub repository releases URL
            gh = FakeGhTransport(
                200,
                {"tag_name": "v2.0.0", "html_url": "https://evil.example/phish", "prerelease": False, "draft": False},
            )
            notice = check_for_update("1.1.0", gh, cache_path=cache_file, clock=lambda: 1000.0)
            self.assertIsNotNone(notice)
            assert notice is not None
            self.assertEqual(notice.latest_version, "2.0.0")
            self.assertTrue(notice.release_url.startswith(REPO_URL + "/"))
            self.assertEqual(gh.calls, 1)

            # Second call within 24h reads from cache with 0 network requests
            notice_cached = check_for_update("1.1.0", gh, cache_path=cache_file, clock=lambda: 2000.0)
            self.assertEqual(notice_cached, notice)
            self.assertEqual(gh.calls, 1)

            # Up-to-date caller gets None
            self.assertIsNone(check_for_update("2.0.0", gh, cache_path=cache_file, clock=lambda: 2000.0))

            # Firewall block / timeout fails open silently
            blocked_gh = FakeGhTransport(fail=True)
            self.assertIsNone(check_for_update("1.1.0", blocked_gh, cache_path=None))

            # Env var and flags disable update check
            self.assertTrue(is_update_check_disabled(disabled_flag=True))
            self.assertTrue(is_update_check_disabled(env={"AZURE_LEGACY_VM_REPORT_NO_UPDATE_CHECK": "1"}))
            self.assertFalse(is_update_check_disabled(env={}))

            # Rendered HTML includes the update link pill while keeping CSP default-src 'none'
            rep = build_report(
                [],
                version="1.1.0",
                generated_at=datetime(2026, 11, 17, 14, 0, tzinfo=UTC),
                tz=UTC,
                tz_name="UTC",
                currency="GBP",
                hours_per_month=730.0,
                policy=HikePolicy(),
                update_notice=notice,
            )
            html_out = render_html(rep)
            self.assertIn("Update available: v2.0.0", html_out)
            self.assertIn(notice.release_url, html_out)
            self.assertIn("default-src 'none'", html_out)
