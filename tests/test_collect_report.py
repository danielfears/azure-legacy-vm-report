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
            version="1.0.0",
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

    def test_target_migration_costs_waves_mg_advisor_ri_and_quota(self) -> None:
        from azure_legacy_vm_report.demo import TENANT_ALPHA
        transport = DemoTransport()
        pricing = PricingClient(transport, currency="GBP", offline=True)
        policy = HikePolicy()
        as_of = datetime(2026, 10, 29, 16, 0, tzinfo=UTC)

        data_alpha = collect_tenant(
            TenantSpec(tenant_id=TENANT_ALPHA),
            tokens=DemoTokens(),
            transport=transport,
            endpoint="https://management.azure.com",
            pricing=pricing,
            policy=policy,
            options=CollectOptions(cost_source=COST_SOURCE_AUTO, as_of=as_of),
        )
        by_name = {r.name: r for r in data_alpha.records}

        # ERP D4_v2 VM: migrates to Standard_D8ds_v5 (preserving local temp disk) at a major saving vs Feb 2027,
        # has Management Group, Advisor right-sizing recommendation, Quota OK, and Wave 1 resize CLI hint
        erp = by_name["vm-erp-app-01"]
        self.assertEqual(erp.management_group, "Production Landing Zones")
        self.assertEqual(erp.target_v5_sku, "Standard_D8ds_v5")
        self.assertLess(erp.target_v5_monthly, erp.feb_monthly)
        self.assertGreater(erp.target_v5_savings_vs_feb, 100.0)
        self.assertLess(erp.target_v5_3yr_ri_monthly, erp.target_v5_monthly)
        self.assertIn("Advisor: Right-size to Standard_D2s_v5", erp.advisor_recommendation)
        self.assertIn("Quota OK", erp.quota_status)
        self.assertIn("Wave 1", erp.migration_wave)
        self.assertIn("az vm resize", erp.migration_cli_hint)

        # SQL DS13_v2 (56 GiB memory-optimised D-series) maps to Standard_E8ds_v5 (64 GiB), not 32 GiB D8s_v5
        sql_vm = by_name["vm-sql-legacy-01"]
        self.assertEqual(sql_vm.target_v5_sku, "Standard_E8ds_v5")

        # AKS systempool VMSS: classified into Wave 2 with az aks nodepool add command
        aks = by_name["aks-systempool-vmss"]
        self.assertIn("Wave 2", aks.migration_wave)
        self.assertIn("az aks nodepool add", aks.migration_cli_hint)

        # Memcache E16s_v3 VM in uksouth is matched to the active Single-subscription RI
        mem1 = by_name["vm-memcache-01"]
        self.assertIn("RI Covered (exp 2027-08-14)", mem1.ri_status)
        self.assertEqual(mem1.ri_expiry_date, "2027-08-14")

    def test_vmss_mtd_extrapolation_zero_row_running_fallback_and_int_billing_month(self) -> None:
        from azure_legacy_vm_report.costmgmt import (
            ActualVmUsage,
            _accumulate_cost_rows,
            _finalise_extrapolation,
            compute_billing_window,
        )
        from azure_legacy_vm_report.model import build_legacy_record
        from azure_legacy_vm_report.pricing import PriceQuote
        from azure_legacy_vm_report.skus import classify_vm_sku

        win = compute_billing_window(datetime(2026, 11, 3, 0, 0, tzinfo=UTC))  # 48h elapsed of 720h
        rid_vm1 = "/subscriptions/s1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1"
        rid_vmss = "/subscriptions/s1/resourcegroups/rg/providers/microsoft.compute/virtualmachinescalesets/vmss10"
        rid_new = "/subscriptions/s1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-new"
        rid_off = "/subscriptions/s1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-dealloc"
        usage_map = {
            rid_vm1: ActualVmUsage(has_data=True),
            rid_vmss: ActualVmUsage(has_data=True),
            rid_new: ActualVmUsage(has_data=True),
            rid_off: ActualVmUsage(has_data=True),
        }
        reply = {
            "properties": {
                "columns": [
                    {"name": "Cost"},
                    {"name": "UsageQuantity"},
                    {"name": "ResourceId"},
                    {"name": "BillingMonth"},
                    {"name": "MeterCategory"},
                    {"name": "Currency"},
                ],
                "rows": [
                    # Integer YYYYMM BillingMonth format
                    [10.0, 40.0, rid_vm1, 202611, "Virtual Machines", "GBP"],
                    [100.0, 400.0, rid_vmss, "202611", "Virtual Machines", "GBP"],
                ],
            }
        }
        _accumulate_cost_rows(reply, usage_map, win)
        _finalise_extrapolation(
            usage_map,
            win,
            instance_counts_by_rid={rid_vm1: 1, rid_vmss: 10},
        )
        # 40h elapsed out of 720h -> 18x scale -> £180.00 (not shrunk 10x by the 10-node VMSS)
        vm1_u = usage_map[rid_vm1]
        self.assertAlmostEqual(vm1_u.mtd_extrapolated_cost, 180.0, places=2)

        d4v2 = classify_vm_sku("Standard_D4_v2")
        assert d4v2 is not None
        quote = PriceQuote(0.5168, "GBP", "D4 v2", "Linux (PAYG)", "fallback-table")

        # Newly deployed running VM with 0 matched CM rows falls back to Retail rather than £0.00
        rec_new = build_legacy_record(
            resource_id="/subscriptions/s1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-new",
            name="vm-new", resource_type="VirtualMachine", tenant_id="t", tenant_name="t",
            subscription_id="s1", subscription_name="s1", resource_group="rg", region="uksouth",
            sku_info=d4v2, instance_count=1, os_type="Linux", license_type="", priority="Regular",
            power_state="Running", quote=quote, policy=HikePolicy(),
            actual_usage=usage_map[rid_new],
        )
        self.assertEqual(rec_new.cost_basis_used, "retail-730h")
        self.assertGreater(rec_new.current_monthly, 300.0)

        # Deallocated VM with 0 matched CM rows remains £0.00 under last-month-actual
        rec_off = build_legacy_record(
            resource_id="/subscriptions/s1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-dealloc",
            name="vm-dealloc", resource_type="VirtualMachine", tenant_id="t", tenant_name="t",
            subscription_id="s1", subscription_name="s1", resource_group="rg", region="uksouth",
            sku_info=d4v2, instance_count=1, os_type="Linux", license_type="", priority="Regular",
            power_state="Deallocated", quote=quote, policy=HikePolicy(),
            actual_usage=usage_map[rid_off],
        )
        self.assertEqual(rec_off.cost_basis_used, "last-month-actual")
        self.assertAlmostEqual(rec_off.current_monthly, 0.0, places=2)

    def test_ri_isf_mg_scope_running_priority_and_fleet_quota(self) -> None:
        from azure_legacy_vm_report.costmgmt import (
            ActiveReservationInfo,
            QuotaFamilyUsage,
            evaluate_quota_headroom,
            match_reservation_for_vm,
        )

        # 1x Standard_E16s_v3 ManagementGroup RI (16 vCPUs, ISF On) scoped to mg-prod
        mg_ri = ActiveReservationInfo(
            reservation_id="r-mg",
            name="ri-mg-e16",
            sku="Standard_E16s_v3",
            region="uksouth",
            quantity=1,
            expiry_date="2027-09-01",
            scope_type="ManagementGroup",
            scope_management_group="mg-prod",
            instance_flexibility="on",
            isf_group="esv3",
            vcpus_per_unit=16,
            remaining_quantity=1,
            remaining_vcpus=16,
        )
        # Deallocated VM does not consume RI capacity
        st_off, _ = match_reservation_for_vm(
            [mg_ri], subscription_id="sub-1", region="uksouth",
            sku="Standard_E16s_v3", parent_sku="Standard_E16s_v3", instance_count=1,
            ri_purchase_blocked=True, vcpus_per_instance=16, power_state="Deallocated",
            mg_ancestors={"mg-prod"},
        )
        self.assertIn("No RI", st_off)
        self.assertEqual(mg_ri.remaining_vcpus, 16)

        # Unrelated Management Group ('mg-dev') does NOT match the mg-prod RI as Shared
        st_other_mg, _ = match_reservation_for_vm(
            [mg_ri], subscription_id="sub-2", region="uksouth",
            sku="Standard_E8s_v3", parent_sku="Standard_E8s_v3", instance_count=1,
            ri_purchase_blocked=True, vcpus_per_instance=8, power_state="Running",
            mg_ancestors={"mg-dev"},
        )
        self.assertIn("No RI", st_other_mg)
        self.assertEqual(mg_ri.remaining_vcpus, 16)

        # Two running Standard_E8s_v3 VMs (8 vCPUs each) in mg-prod are both covered via ISF!
        st_run1, _ = match_reservation_for_vm(
            [mg_ri], subscription_id="sub-1", region="uksouth",
            sku="Standard_E8s_v3", parent_sku="Standard_E8s_v3", instance_count=1,
            ri_purchase_blocked=True, vcpus_per_instance=8, power_state="Running",
            mg_ancestors={"mg-prod"},
        )
        st_run2, _ = match_reservation_for_vm(
            [mg_ri], subscription_id="sub-1", region="uksouth",
            sku="Standard_E8s_v3", parent_sku="Standard_E8s_v3", instance_count=1,
            ri_purchase_blocked=True, vcpus_per_instance=8, power_state="Running",
            mg_ancestors={"mg-prod"},
        )
        self.assertIn("RI Covered", st_run1)
        self.assertIn("RI Covered", st_run2)
        self.assertEqual(mg_ri.remaining_vcpus, 0)

        # Cumulative fleet quota check catches subscription-wide shortfall even when 1 VM fits
        q_map = {
            ("sub-1", "uksouth", "standardddsv5family"): QuotaFamilyUsage(
                family_name="standardDDSv5Family", localized_name="Standard DDSv5", current_value=84, limit=100
            )
        }
        q_status = evaluate_quota_headroom(
            q_map, subscription_id="sub-1", region="uksouth",
            target_quota_family="standardDDSv5Family", needed_vcpus=8, fleet_needed_vcpus=24,
        )
        self.assertIn("Quota Increase Needed", q_status)
        self.assertIn("fleet needs 24", q_status)

    def test_arm_fallback_deduplicates_flexible_vmss_and_auth_expiry_strings(self) -> None:
        from azure_legacy_vm_report.auth import AzCli, AzCliTokenProvider

        provider = AzCliTokenProvider(AzCli(executable="az"), "https://management.azure.com/", clock=lambda: 1000.0)
        self.assertEqual(provider._expiry({"expires_on": "1763376000"}), 1763376000.0)
        self.assertGreater(provider._expiry({"expiresOn": "2026-11-17 12:00:00"}), 1700000000.0)

        class FlexArmTransport(FallbackComputeTransport):
            def request(self, method, url, headers, body, timeout):
                parsed = urllib.parse.urlsplit(url)
                vms_path = f"/subscriptions/{SUB_ID}/providers/Microsoft.Compute/virtualMachines"
                if parsed.path == vms_path:
                    vmss_id = (
                        f"/subscriptions/{SUB_ID}/resourceGroups/rg-1/providers/"
                        "Microsoft.Compute/virtualMachineScaleSets/vmss-v3"
                    )
                    child_id = (
                        f"/subscriptions/{SUB_ID}/resourceGroups/rg-1/providers/"
                        "Microsoft.Compute/virtualMachines/vmss-v3_0"
                    )
                    return _resp({
                        "value": [
                            {
                                "id": child_id,
                                "name": "vmss-v3_0",
                                "location": "uksouth",
                                "properties": {
                                    "virtualMachineScaleSet": {"id": vmss_id},
                                    "hardwareProfile": {"vmSize": "Standard_D4s_v3"},
                                    "storageProfile": {"osDisk": {"osType": "Linux"}},
                                    "instanceView": {"statuses": [{"code": "PowerState/running"}]},
                                },
                            }
                        ]
                    })
                return super().request(method, url, headers, body, timeout)

        transport = FlexArmTransport()
        pricing = PricingClient(transport, currency="GBP", offline=True)
        data = collect_tenant(
            TenantSpec(tenant_id=TENANT_ID),
            tokens=StaticTokens(),
            transport=transport,
            endpoint="https://management.azure.com",
            pricing=pricing,
            policy=HikePolicy(),
            options=CollectOptions(use_resource_graph=False),
        )
        # Parent Flexible VMSS is skipped because its child VM is present -> 1 instance, not 4!
        self.assertEqual(len(data.records), 1)
        self.assertEqual(data.records[0].name, "vmss-v3_0")
        self.assertEqual(data.records[0].instance_count, 1)



