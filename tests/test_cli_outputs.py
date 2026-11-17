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
