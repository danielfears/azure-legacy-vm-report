"""Synthetic dataset for ``--demo`` and offline end-to-end testing."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .auth import AccessToken, TokenProvider
from .config import TenantSpec
from .transport import Response, Transport

TENANT_ALPHA = "11111111-1111-4111-8111-111111111111"
TENANT_BETA = "22222222-2222-4222-8222-222222222222"

SUB_CORE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
SUB_DATA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"
SUB_SHARED = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"
SUB_DEV = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"


def build_demo_specs() -> List[TenantSpec]:
    return [
        TenantSpec(tenant_id=TENANT_ALPHA, name="Contoso Production (Demo)"),
        TenantSpec(tenant_id=TENANT_BETA, name="Contoso Development (Demo)"),
    ]


class DemoTokens(TokenProvider):
    def get_token(self, tenant_id: str) -> AccessToken:
        tid = tenant_id.lower()
        return AccessToken(token=f"demo-token-{tid}", expires_on=9999999999.0, tenant_id=tid)


class DemoTransport(Transport):
    """Fake ARM + Cost Management + Retail Prices transport for ``--demo``."""

    def __init__(self) -> None:
        self._alpha_vms = _alpha_resources()
        self._beta_vms = _beta_resources()

    def request(
        self, method: str, url: str, headers: Mapping[str, str], body: Optional[bytes], timeout: float,
    ) -> Response:
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname == "prices.azure.com":
            return Response(200, {"content-type": "application/json"}, json.dumps({"Items": []}).encode("utf-8"))

        auth = str(headers.get("Authorization") or "")
        is_alpha = TENANT_ALPHA in auth
        path = parsed.path

        if path == "/tenants":
            payload = {
                "value": [
                    {
                        "tenantId": TENANT_ALPHA,
                        "displayName": "Contoso Production (Demo)",
                        "defaultDomain": "prod.contoso.example",
                    },
                    {
                        "tenantId": TENANT_BETA,
                        "displayName": "Contoso Development (Demo)",
                        "defaultDomain": "dev.contoso.example",
                    },
                ]
            }
            return _json_response(payload)

        if path == "/subscriptions":
            if is_alpha:
                subs = [
                    {"subscriptionId": SUB_CORE, "displayName": "CONTOSO-CORE-INFRA-PROD-001", "state": "Enabled"},
                    {"subscriptionId": SUB_DATA, "displayName": "CONTOSO-DATA-PLATFORM-PROD-002", "state": "Enabled"},
                    {"subscriptionId": SUB_SHARED, "displayName": "CONTOSO-SHARED-SERVICES-PROD-001", "state": "Enabled"},
                ]
            else:
                subs = [
                    {"subscriptionId": SUB_DEV, "displayName": "CONTOSO-WORKLOAD-SANDBOX-DEV-001", "state": "Enabled"},
                ]
            return _json_response({"value": subs})

        if path == "/providers/Microsoft.ResourceGraph/resources" and method == "POST":
            req_json = json.loads(body.decode("utf-8")) if body else {}
            query_str = str(req_json.get("query") or "").lower()
            if "microsoft.devtestlab/schedules" in query_str:
                return _json_response({"data": [] if is_alpha else _beta_schedules()})
            rows = self._alpha_vms if is_alpha else self._beta_vms
            return _json_response({"data": rows})

        if path.endswith("/providers/Microsoft.CostManagement/query") and method == "POST":
            req_json = json.loads(body.decode("utf-8")) if body else {}
            return _json_response(_demo_cost_response(path, req_json))

        return Response(404, {"content-type": "application/json"}, b'{"error":{"code":"NotFound"}}')


def _json_response(payload: Dict[str, Any], status: int = 200) -> Response:
    return Response(status, {"content-type": "application/json"}, json.dumps(payload).encode("utf-8"))


def _vm_row(
    sub_id: str,
    rg: str,
    name: str,
    region: str,
    sku: str,
    *,
    os_type: str = "Linux",
    license_type: str = "",
    power: str = "PowerState/running",
    is_vmss: bool = False,
    capacity: int = 1,
    tags: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    rtype = "Microsoft.Compute/virtualMachineScaleSets" if is_vmss else "Microsoft.Compute/virtualMachines"
    rid = f"/subscriptions/{sub_id}/resourceGroups/{rg}/providers/{rtype}/{name}"
    return {
        "id": rid,
        "name": name,
        "type": rtype,
        "subscriptionId": sub_id,
        "resourceGroup": rg,
        "location": region,
        "tags": tags or {},
        "vmSize": "" if is_vmss else sku,
        "skuName": sku if is_vmss else "",
        "skuCapacity": capacity,
        "osType": os_type,
        "licenseType": license_type,
        "priority": "Regular",
        "powerState": power,
    }


def _alpha_resources() -> List[Dict[str, Any]]:
    return [
        # v1 legacy SKUs
        _vm_row(SUB_CORE, "rg-identity-prd-uks-001", "vm-dc-legacy-01", "uksouth", "Standard_DS2", os_type="Windows"),
        _vm_row(SUB_CORE, "rg-identity-prd-uks-001", "vm-dc-legacy-02", "ukwest", "Standard_DS2", os_type="Windows"),
        _vm_row(SUB_SHARED, "rg-bastion-prd-uks-001", "vm-jump-b2s-01", "uksouth", "Standard_B2s", os_type="Linux"),
        _vm_row(SUB_SHARED, "rg-bastion-prd-uks-001", "vm-jump-b4ms-01", "uksouth", "Standard_B4ms", os_type="Windows", license_type="Windows_Server"),
        _vm_row(SUB_DATA, "rg-ingest-prd-uks-001", "vm-parser-f4s-01", "uksouth", "Standard_F4s", os_type="Linux"),
        # v2 legacy SKUs
        _vm_row(SUB_CORE, "rg-app-prd-uks-001", "vm-erp-app-01", "uksouth", "Standard_D4_v2", os_type="Windows"),
        _vm_row(SUB_CORE, "rg-app-prd-uks-001", "vm-erp-app-02", "uksouth", "Standard_D4_v2", os_type="Windows"),
        _vm_row(SUB_DATA, "rg-sql-prd-uks-001", "vm-sql-legacy-01", "uksouth", "Standard_DS13_v2", os_type="Windows", license_type="Windows_Server"),
        _vm_row(SUB_DATA, "rg-etl-prd-uks-001", "vmss-etl-workers", "uksouth", "Standard_F8s_v2", os_type="Linux", is_vmss=True, capacity=4),
        _vm_row(SUB_SHARED, "rg-cmg-prd-uks-001", "vm-cmg-proxy-01", "uksouth", "Standard_A4_v2", os_type="Windows"),
        # v3 legacy SKUs
        _vm_row(
            SUB_CORE,
            "MC_rg-aks-prd-uks-001_aks-core-prd_uksouth",
            "aks-systempool-vmss",
            "uksouth",
            "Standard_D8s_v3",
            os_type="Linux",
            is_vmss=True,
            capacity=6,
            tags={"aks-managed-poolName": "systempool"},
        ),
        _vm_row(SUB_DATA, "rg-cache-prd-uks-001", "vm-memcache-01", "uksouth", "Standard_E16s_v3", os_type="Linux"),
        _vm_row(SUB_DATA, "rg-cache-prd-uks-001", "vm-memcache-02", "ukwest", "Standard_E16s_v3", os_type="Linux"),
        _vm_row(SUB_SHARED, "rg-eu-relay-prd-neu-001", "vm-dublin-relay-01", "northeurope", "Standard_D4s_v3", os_type="Linux"),
        _vm_row(SUB_CORE, "rg-dr-cold-ukw-001", "vm-dr-standby-01", "ukwest", "Standard_D8s_v3", os_type="Windows", power="PowerState/deallocated"),
        # Modern v5/v6 SKUs (should be scanned and skipped as non-legacy)
        _vm_row(SUB_CORE, "rg-modern-prd-uks-001", "vm-modern-v5-01", "uksouth", "Standard_D4s_v5", os_type="Linux"),
        _vm_row(SUB_CORE, "rg-modern-prd-uks-001", "vm-modern-v6-01", "uksouth", "Standard_D4s_v6", os_type="Linux"),
    ]


def _beta_resources() -> List[Dict[str, Any]]:
    return [
        _vm_row(SUB_DEV, "rg-dev-uks-001", "vm-dev-b2ms-01", "uksouth", "Standard_B2ms", os_type="Linux"),
        _vm_row(SUB_DEV, "rg-dev-uks-001", "vm-dev-ds3v2-01", "uksouth", "Standard_DS3_v2", os_type="Linux"),
        _vm_row(
            SUB_DEV,
            "rg-dev-uks-001",
            "vm-dev-d4sv3-01",
            "westeurope",
            "Standard_D4s_v3",
            os_type="Windows",
            license_type="Windows_Server",
            tags={"Autostartup": "true", "Autoshutdown": "true"},
        ),
        _vm_row(SUB_DEV, "rg-dev-uks-001", "vm-dev-stopped-01", "uksouth", "Standard_D2s_v3", os_type="Linux", power="PowerState/deallocated"),
    ]


def _beta_schedules() -> List[Dict[str, Any]]:
    return [
        {
            "name": "shutdown-computevm-vm-dev-b2ms-01",
            "properties": {
                "status": "Enabled",
                "targetResourceId": f"/subscriptions/{SUB_DEV}/resourceGroups/rg-dev-uks-001/providers/Microsoft.Compute/virtualMachines/vm-dev-b2ms-01",
                "dailyRecurrence": {"time": "1900"},
                "timeZoneId": "GMT Standard Time",
            },
        },
        {
            "name": "shutdown-computevm-vm-dev-ds3v2-01",
            "properties": {
                "status": "Enabled",
                "targetResourceId": f"/subscriptions/{SUB_DEV}/resourceGroups/rg-dev-uks-001/providers/Microsoft.Compute/virtualMachines/vm-dev-ds3v2-01",
                "dailyRecurrence": {"time": "1900"},
                "timeZoneId": "GMT Standard Time",
            },
        },
    ]


# Synthetic last-month and MTD usage: (last_month_cost_gbp, last_month_hours, mtd_cost_gbp, mtd_hours)
_DEMO_COSTS: Dict[str, Tuple[float, float, float, float]] = {
    "vm-dc-legacy-01": (152.20, 720.0, 143.75, 680.0),
    "vm-dc-legacy-02": (156.80, 720.0, 148.09, 680.0),
    "vm-jump-b2s-01": (25.33, 720.0, 23.92, 680.0),
    "vm-jump-b4ms-01": (101.18, 720.0, 95.56, 680.0),
    "vm-parser-f4s-01": (128.77, 720.0, 121.62, 680.0),
    "vm-erp-app-01": (632.03, 720.0, 596.92, 680.0),
    "vm-erp-app-02": (632.03, 720.0, 596.92, 680.0),
    "vm-sql-legacy-01": (475.96, 720.0, 449.52, 680.0),
    "vmss-etl-workers": (868.41, 2880.0, 820.17, 2720.0),
    "vm-cmg-proxy-01": (188.63, 720.0, 178.15, 680.0),
    "aks-systempool-vmss": (1496.21, 4320.0, 1413.09, 4080.0),
    "vm-memcache-01": (670.72, 720.0, 633.46, 680.0),
    "vm-memcache-02": (690.87, 720.0, 652.49, 680.0),
    "vm-dublin-relay-01": (119.72, 720.0, 113.07, 680.0),
    "vm-dr-standby-01": (0.0, 0.0, 0.0, 0.0),
    # Scheduled dev VMs run ~240h/month instead of 730h/month!
    "vm-dev-b2ms-01": (16.63, 240.0, 15.71, 226.0),
    "vm-dev-ds3v2-01": (62.02, 240.0, 58.57, 226.0),
    "vm-dev-d4sv3-01": (127.17, 720.0, 120.10, 680.0),
    "vm-dev-stopped-01": (12.47, 146.0, 0.0, 0.0),
}


def _demo_cost_response(path: str, req_json: Mapping[str, Any]) -> Dict[str, Any]:
    tp = req_json.get("timePeriod") if isinstance(req_json.get("timePeriod"), dict) else {}
    from_str = str(tp.get("from") or "2026-09-01")[:7]
    to_str = str(tp.get("to") or "2026-10-29")[:7]
    last_month_val = f"{from_str}-01T00:00:00"
    cur_month_val = f"{to_str}-01T00:00:00"

    all_vms = _alpha_resources() + _beta_resources()
    parts = path.strip("/").split("/")
    sub_id = parts[1].lower() if len(parts) >= 2 else ""

    rows: List[List[Any]] = []
    for vm in all_vms:
        if str(vm.get("subscriptionId") or "").lower() != sub_id:
            continue
        name = str(vm.get("name") or "")
        rid = str(vm.get("id") or "")
        entry = _DEMO_COSTS.get(name)
        if not entry:
            continue
        lm_cost, lm_hrs, mtd_cost, mtd_hrs = entry
        rows.append([lm_cost, lm_hrs, rid, last_month_val, "Virtual Machines", "GBP"])
        rows.append([mtd_cost, mtd_hrs, rid, cur_month_val, "Virtual Machines", "GBP"])

    return {
        "properties": {
            "columns": [
                {"name": "Cost", "type": "Number"},
                {"name": "UsageQuantity", "type": "Number"},
                {"name": "ResourceId", "type": "String"},
                {"name": "BillingMonth", "type": "String"},
                {"name": "MeterCategory", "type": "String"},
                {"name": "Currency", "type": "String"},
            ],
            "rows": rows,
        }
    }

