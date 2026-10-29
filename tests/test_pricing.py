"""Unit tests for Azure Retail Prices API parsing, fallback rates and February 2027 hike rules."""

from __future__ import annotations

import json
import unittest
from typing import Mapping, Optional

from azure_legacy_vm_report.pricing import (
    POLICY_CUSTOM,
    POLICY_LEGACY_25,
    POLICY_SERVICE_HEALTH,
    HikePolicy,
    PricingClient,
    effective_os_meter,
    uses_hybrid_benefit,
)
from azure_legacy_vm_report.skus import classify_vm_sku
from azure_legacy_vm_report.transport import Response, Transport


class FakePricingTransport(Transport):
    def __init__(self, items):
        self.items = items
        self.calls = 0

    def request(
        self, method: str, url: str, headers: Mapping[str, str], body: Optional[bytes], timeout: float,
    ) -> Response:
        self.calls += 1
        payload = {"Items": self.items}
        return Response(200, {"content-type": "application/json"}, json.dumps(payload).encode("utf-8"))


class PricingTests(unittest.TestCase):
    def test_hybrid_benefit_uses_linux_base_meter(self) -> None:
        self.assertTrue(uses_hybrid_benefit("Windows", "Windows_Server"))
        self.assertTrue(uses_hybrid_benefit("Windows", "Windows_Client"))
        self.assertTrue(uses_hybrid_benefit("Linux", "RHEL_BYOS"))
        self.assertFalse(uses_hybrid_benefit("Windows", ""))
        self.assertEqual(effective_os_meter("Windows", "Windows_Server"), "Linux")
        self.assertEqual(effective_os_meter("Windows", ""), "Windows")
        self.assertEqual(effective_os_meter("Linux", ""), "Linux")

    def test_retail_api_selects_correct_meter_and_caches(self) -> None:
        items = [
            {
                "armSkuName": "Standard_D4s_v3",
                "productName": "Virtual Machines DSv3 Series",
                "skuName": "D4s v3",
                "meterName": "D4s v3",
                "type": "Consumption",
                "retailPrice": 0.1708,
                "currencyCode": "GBP",
                "effectiveStartDate": "2024-01-01T00:00:00Z",
            },
            {
                "armSkuName": "Standard_D4s_v3",
                "productName": "Virtual Machines DSv3 Series Windows",
                "skuName": "D4s v3",
                "meterName": "D4s v3",
                "type": "Consumption",
                "retailPrice": 0.3063,
                "currencyCode": "GBP",
                "effectiveStartDate": "2024-01-01T00:00:00Z",
            },
            {
                "armSkuName": "Standard_D4s_v3",
                "productName": "Virtual Machines DSv3 Series",
                "skuName": "D4s v3 Spot",
                "meterName": "D4s v3 Spot",
                "type": "Consumption",
                "retailPrice": 0.0371,
                "currencyCode": "GBP",
                "effectiveStartDate": "2026-10-01T00:00:00Z",
            },
        ]
        transport = FakePricingTransport(items)
        client = PricingClient(transport, currency="GBP")
        sku = classify_vm_sku("Standard_D4s_v3")
        assert sku is not None

        q_linux = client.quote(sku, "uksouth", os_type="Linux")
        self.assertAlmostEqual(q_linux.hourly_rate, 0.1708)
        self.assertEqual(q_linux.source, "retail-api")

        q_win = client.quote(sku, "uksouth", os_type="Windows")
        self.assertAlmostEqual(q_win.hourly_rate, 0.3063)

        q_ahb = client.quote(sku, "uksouth", os_type="Windows", license_type="Windows_Server")
        self.assertAlmostEqual(q_ahb.hourly_rate, 0.1708)

        q_spot = client.quote(sku, "uksouth", os_type="Linux", priority="Spot")
        self.assertAlmostEqual(q_spot.hourly_rate, 0.0371)

        # Cached by (region, arm_sku) so only 1 HTTP call was needed
        self.assertEqual(transport.calls, 1)

    def test_hike_policy_models(self) -> None:
        v1_sku = classify_vm_sku("Standard_B2s")
        v2_sku = classify_vm_sku("Standard_D4_v2")
        bsv2_sku = classify_vm_sku("Standard_B2as_v2")
        v3_sku = classify_vm_sku("Standard_D4s_v3")
        assert v1_sku and v2_sku and bsv2_sku and v3_sku

        p_legacy = HikePolicy(name=POLICY_LEGACY_25, v1_hike_pct=25.0, v2_hike_pct=25.0, v3_hike_pct=25.0, apply_regional_to_v3=False)
        self.assertEqual(p_legacy.hike_pct_for(v1_sku, "uksouth")[0], 25.0)
        self.assertEqual(p_legacy.hike_pct_for(v2_sku, "uksouth")[0], 25.0)
        self.assertEqual(p_legacy.hike_pct_for(v3_sku, "uksouth")[0], 25.0)

        p_sh = HikePolicy(name=POLICY_SERVICE_HEALTH, v1_hike_pct=25.0, v2_hike_pct=25.0, v3_hike_pct=0.0)
        self.assertEqual(p_sh.hike_pct_for(v1_sku, "uksouth")[0], 25.0)
        self.assertEqual(p_sh.hike_pct_for(v2_sku, "westeurope")[0], 25.0)
        self.assertEqual(p_sh.hike_pct_for(bsv2_sku, "uksouth")[0], 0.0)
        self.assertEqual(p_sh.hike_pct_for(bsv2_sku, "westeurope")[0], 9.0)
        self.assertEqual(p_sh.hike_pct_for(v3_sku, "uksouth")[0], 0.0)
        self.assertEqual(p_sh.hike_pct_for(v3_sku, "northeurope")[0], 17.0)
        self.assertEqual(p_sh.hike_pct_for(v3_sku, "westeurope")[0], 9.0)
        self.assertEqual(p_sh.hike_pct_for(v3_sku, "francecentral")[0], 11.0)
        self.assertEqual(p_sh.hike_pct_for(v3_sku, "southeastasia")[0], 8.0)

        p_custom = HikePolicy(name=POLICY_CUSTOM, v1_hike_pct=30.0, v2_hike_pct=25.0, v3_hike_pct=15.0)
        self.assertEqual(p_custom.hike_pct_for(v1_sku, "uksouth")[0], 30.0)
        self.assertEqual(p_custom.hike_pct_for(v2_sku, "uksouth")[0], 25.0)
        self.assertEqual(p_custom.hike_pct_for(v3_sku, "uksouth")[0], 15.0)
