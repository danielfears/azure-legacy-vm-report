"""Unit tests for tenant collection (Resource Graph + Compute API fallback) and report aggregation."""

from __future__ import annotations

import json
import unittest
import urllib.parse
from datetime import datetime
from typing import Dict, Mapping, Optional

from azure_legacy_vm_report.auth import AccessToken, TokenProvider
from azure_legacy_vm_report.collect import CollectOptions, collect_tenant
from azure_legacy_vm_report.config import TenantSpec
from azure_legacy_vm_report.dates import UTC
from azure_legacy_vm_report.demo import TENANT_BETA, DemoTokens, DemoTransport
from azure_legacy_vm_report.model import COST_SOURCE_AUTO, COST_SOURCE_RETAIL
from azure_legacy_vm_report.pricing import HikePolicy, PricingClient
from azure_legacy_vm_report.report import build_report
from azure_legacy_vm_report.transport import Response, Transport

TENANT_ID = "11111111-1111-4111-8111-111111111111"
SUB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"


class StaticTokens(TokenProvider):
    def get_token(self, tenant_id: str) -> AccessToken:
        return AccessToken(token="fake-token", expires_on=9999999999.0, tenant_id=TENANT_ID)


class FallbackComputeTransport(Transport):
    """Simulates Azure Resource Graph returning 403 so collection falls back to Microsoft.Compute."""

    def request(
        self, method: str, url: str, headers: Mapping[str, str], body: Optional[bytes], timeout: float,
    ) -> Response:
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path
        if path == "/tenants":
            return _resp({"value": [{"tenantId": TENANT_ID, "displayName": "Test Tenant", "defaultDomain": "test.local"}]})
        if path == "/subscriptions":
            return _resp({"value": [{"subscriptionId": SUB_ID, "displayName": "Sub-Prod-01"}]})
        if path == "/providers/Microsoft.ResourceGraph/resources":
            return _resp({"error": {"code": "AuthorizationFailed", "message": "ARG denied"}}, status=403)
        if path == f"/subscriptions/{SUB_ID}/providers/Microsoft.Compute/virtualMachines":
            return _resp({
                "value": [
                    {
                        "id": f"/subscriptions/{SUB_ID}/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-v2",
                        "name": "vm-v2",
                        "location": "uksouth",
                        "properties": {
                            "hardwareProfile": {"vmSize": "Standard_D4_v2"},
                            "storageProfile": {"osDisk": {"osType": "Linux"}},
                            "instanceView": {"statuses": [{"code": "PowerState/running"}]},
                        },
                    },
                    {
                        "id": f"/subscriptions/{SUB_ID}/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-v5",
                        "name": "vm-v5",
                        "location": "uksouth",
                        "properties": {
                            "hardwareProfile": {"vmSize": "Standard_D4s_v5"},
                            "storageProfile": {"osDisk": {"osType": "Linux"}},
                            "instanceView": {"statuses": [{"code": "PowerState/running"}]},
                        },
                    },
                ]
            })
        if path == f"/subscriptions/{SUB_ID}/providers/Microsoft.Compute/virtualMachineScaleSets":
            return _resp({
                "value": [
                    {
                        "id": f"/subscriptions/{SUB_ID}/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachineScaleSets/vmss-v3",
                        "name": "vmss-v3",
                        "location": "uksouth",
                        "sku": {"name": "Standard_D4s_v3", "capacity": 3},
                        "properties": {
                            "virtualMachineProfile": {
                                "storageProfile": {"osDisk": {"osType": "Linux"}},
                            }
                        },
                    }
                ]
            })
        return _resp({"error": {"code": "NotFound"}}, status=404)


def _resp(payload: Dict, status: int = 200) -> Response:
    return Response(status, {"content-type": "application/json"}, json.dumps(payload).encode("utf-8"))


class CollectAndReportTests(unittest.TestCase):
    def test_fallback_to_compute_arm_and_report_totals(self) -> None:
        transport = FallbackComputeTransport()
        pricing = PricingClient(transport, currency="GBP", offline=True)
        policy = HikePolicy()
        options = CollectOptions()

        data = collect_tenant(
            TenantSpec(tenant_id=TENANT_ID),
            tokens=StaticTokens(),
            transport=transport,
            endpoint="https://management.azure.com",
            pricing=pricing,
            policy=policy,
            options=options,
        )
        self.assertFalse(data.fatal)
        self.assertEqual(data.discovery_method, "ARM Microsoft.Compute API")
        self.assertEqual(data.total_resources_scanned, 3)
        self.assertEqual(data.modern_resources_skipped, 1)
        self.assertEqual(len(data.records), 2)

        report = build_report(
            [data],
            version="0.1.0",
            generated_at=datetime(2026, 10, 28, 16, 0, tzinfo=UTC),
            tz=UTC,
            tz_name="UTC",
            currency="GBP",
            hours_per_month=730.0,
            policy=policy,
        )
        gt = report.grand_total()
        self.assertEqual(gt.resource_count, 2)
        self.assertEqual(gt.instance_count, 4)  # 1 VM + 3 VMSS instances
        by_gen = report.totals_by_generation()
        self.assertAlmostEqual(by_gen["v2"].effective_hike_pct, 25.0, places=1)
        self.assertAlmostEqual(by_gen["v3"].effective_hike_pct, 0.0, places=1)
        self.assertAlmostEqual(gt.monthly_delta, by_gen["v2"].monthly_delta, places=2)

    def test_cost_management_actuals_and_schedules_vs_retail_fallback(self) -> None:
        transport = DemoTransport()
        pricing = PricingClient(transport, currency="GBP", offline=True)
        policy = HikePolicy()
        as_of = datetime(2026, 10, 29, 16, 0, tzinfo=UTC)

        data_cm = collect_tenant(
            TenantSpec(tenant_id=TENANT_BETA),
            tokens=DemoTokens(),
            transport=transport,
            endpoint="https://management.azure.com",
            pricing=pricing,
            policy=policy,
            options=CollectOptions(cost_source=COST_SOURCE_AUTO, as_of=as_of),
        )
        by_name_cm = {r.name: r for r in data_cm.records}
        b2ms_cm = by_name_cm["vm-dev-b2ms-01"]
        self.assertEqual(b2ms_cm.auto_shutdown_schedule, "Enabled (19:00)")
        self.assertEqual(b2ms_cm.cost_basis_used, "last-month-actual")
        self.assertAlmostEqual(b2ms_cm.current_monthly, 16.63, places=2)
        self.assertAlmostEqual(b2ms_cm.actual_last_month_hours or 0.0, 240.0, places=1)

        # Deallocated VM that ran 146h last month still shows its real £12.47 spend from last month
        stopped_cm = by_name_cm["vm-dev-stopped-01"]
        self.assertAlmostEqual(stopped_cm.current_monthly, 12.47, places=2)

        # In retail mode, the same running B2ms VM is costed at 730h/mo (£50.59) and deallocated at £0.00
        data_retail = collect_tenant(
            TenantSpec(tenant_id=TENANT_BETA),
            tokens=DemoTokens(),
            transport=transport,
            endpoint="https://management.azure.com",
            pricing=pricing,
            policy=policy,
            options=CollectOptions(cost_source=COST_SOURCE_RETAIL, as_of=as_of),
        )
        by_name_ret = {r.name: r for r in data_retail.records}
        self.assertEqual(by_name_ret["vm-dev-b2ms-01"].cost_basis_used, "retail-730h")
        self.assertAlmostEqual(by_name_ret["vm-dev-b2ms-01"].current_monthly, 50.59, places=2)
        self.assertAlmostEqual(by_name_ret["vm-dev-stopped-01"].current_monthly, 0.0, places=2)
        # Runbook-tagged VM has inferred 260h/mo schedule
        d4s_ret = by_name_ret["vm-dev-d4sv3-01"]
        self.assertIn("Runbook: Autostartup+Autoshutdown", d4s_ret.auto_shutdown_schedule)
        self.assertAlmostEqual(d4s_ret.inferred_hours_per_month, 260.0, places=1)
        self.assertLess(d4s_ret.schedule_adjusted_monthly, d4s_ret.retail_active_monthly)



