"""Azure VM pricing lookup (Azure Retail Prices API + offline fallback) and February 2027 hike calculation."""

from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .skus import GEN_V1, GEN_V2, GEN_V3, SkuInfo, classify_vm_sku
from .transport import Transport, TransportError

log = logging.getLogger("azure_legacy_vm_report.pricing")

DEFAULT_HOURS_PER_MONTH = 730.0
DEFAULT_CURRENCY = "GBP"
RETAIL_PRICES_ENDPOINT = "https://prices.azure.com/api/retail/prices"

POLICY_LEGACY_25 = "legacy-25"
POLICY_SERVICE_HEALTH = "service-health"
POLICY_CUSTOM = "custom"
VALID_POLICIES = (POLICY_LEGACY_25, POLICY_SERVICE_HEALTH, POLICY_CUSTOM)

# Regional February 2027 price hikes announced in the October 2026 Service Health advisory
# for non-excluded VM series (which includes v3 series such as Dv3, Dsv3, Ev3, Esv3).
REGIONAL_FEB_2027_HIKES: Dict[str, float] = {
    "northeurope": 17.0,
    "francecentral": 11.0,
    "francesouth": 11.0,
    "westeurope": 9.0,
    "norwayeast": 9.0,
    "norwaywest": 9.0,
    "southeastasia": 8.0,
}

# Verified baseline UK South per-vCPU hourly rates (GBP and USD) from the Azure Retail Prices API
# (October 2026) used as an offline fallback when --offline-prices is requested or when a retired
# SKU meter is omitted from the live API.
_SERIES_PER_VCPU_GBP: Dict[str, Tuple[float, float]] = {
    # series: (linux_per_vcpu_gbp, windows_per_vcpu_gbp)
    "Av1": (0.0440, 0.0680),
    "Basic_A": (0.0180, 0.0320),
    "Av2": (0.0352, 0.0610),
    "Amv2": (0.0495, 0.0750),
    "Bv1": (0.0176, 0.0206),
    "Bsv2": (0.0168, 0.0202),
    "Basv2": (0.0152, 0.0186),
    "Bpsv2": (0.0138, 0.0172),
    "D": (0.0725, 0.1070),
    "Ds": (0.0725, 0.1070),
    "Dv1": (0.0725, 0.1070),
    "Dsv1": (0.0725, 0.1070),
    "Dv2": (0.0647, 0.1082),
    "Dsv2": (0.0647, 0.1082),
    "Dv3": (0.0427, 0.0766),
    "Dsv3": (0.0427, 0.0766),
    "Ev3": (0.0574, 0.0913),
    "Esv3": (0.0574, 0.0913),
    "F": (0.0450, 0.0790),
    "Fs": (0.0450, 0.0790),
    "Fsv2": (0.0372, 0.0710),
    "G": (0.1650, 0.2150),
    "Gs": (0.1650, 0.2150),
    "Ls": (0.0660, 0.1000),
    "Lsv1": (0.0660, 0.1000),
    "Lsv2": (0.0620, 0.0960),
    "Lsv3": (0.0580, 0.0920),
    "Lasv3": (0.0520, 0.0860),
    "DCs": (0.0850, 0.1190),
    "DCsv2": (0.0850, 0.1190),
    "DCsv3": (0.0610, 0.0950),
    "DCdsv3": (0.0680, 0.1020),
    "HB": (0.0260, 0.0420),
    "HBv2": (0.0260, 0.0420),
    "HC": (0.0650, 0.0950),
    "H": (0.0850, 0.1150),
    "NP": (0.1250, 0.1590),
    "M": (0.1150, 0.1490),
    "Msv2/Mdsv2": (0.1250, 0.1590),
    "NVv3": (0.0950, 0.1290),
    "NCv3": (0.3800, 0.4140),
    "NCasT4_v3": (0.0820, 0.1160),
    # Modern v4/v5/v6 target & regional-hike series
    "Dv4": (0.0427, 0.0766),
    "Dsv4": (0.0427, 0.0766),
    "Ev4": (0.0574, 0.0913),
    "Esv4": (0.0574, 0.0913),
    "Dv5": (0.0427, 0.0766),
    "Dsv5": (0.0427, 0.0766),
    "Dlsv5": (0.0362, 0.0701),
    "Ev5": (0.0574, 0.0913),
    "Esv5": (0.0574, 0.0913),
    "Dv6": (0.0448, 0.0787),
    "Dsv6": (0.0448, 0.0787),
    "Dlsv6": (0.0378, 0.0717),
    "Ev6": (0.0602, 0.0941),
    "Esv6": (0.0602, 0.0941),
    "Fsv6": (0.0378, 0.0717),
    "Falsv6": (0.0378, 0.0717),
    "Lsv4": (0.0595, 0.0935),
    "DCasv5": (0.0480, 0.0820),
    "DCasv6": (0.0500, 0.0840),
}

# Exact verified UK South hourly rates in GBP (and USD via 1.36215 conversion when needed)
_EXACT_UKS_GBP: Dict[str, Tuple[float, float]] = {
    "Standard_B1ls": (0.0043, 0.0073),
    "Standard_B1s": (0.0087, 0.0117),
    "Standard_B1ms": (0.0173, 0.0203),
    "Standard_B2s": (0.0347, 0.0406),
    "Standard_B2ms": (0.0693, 0.0811),
    "Standard_B4ms": (0.1386, 0.1621),
    "Standard_B8ms": (0.2773, 0.3243),
    "Standard_B12ms": (0.4159, 0.4864),
    "Standard_B16ms": (0.5546, 0.6485),
    "Standard_B20ms": (0.6932, 0.8106),
    "Standard_D1": (0.0706, 0.1042),
    "Standard_DS1": (0.0706, 0.1042),
    "Standard_D2": (0.1412, 0.2085),
    "Standard_DS2": (0.1412, 0.2085),
    "Standard_D3": (0.2825, 0.4170),
    "Standard_DS3": (0.2825, 0.4170),
    "Standard_D4": (0.5650, 0.8340),
    "Standard_DS4": (0.5650, 0.8340),
    "Standard_D1_v2": (0.0646, 0.1079),
    "Standard_DS1_v2": (0.0646, 0.1079),
    "Standard_D2_v2": (0.1292, 0.2158),
    "Standard_DS2_v2": (0.1292, 0.2158),
    "Standard_D3_v2": (0.2584, 0.4329),
    "Standard_DS3_v2": (0.2584, 0.4329),
    "Standard_D4_v2": (0.5168, 0.8658),
    "Standard_DS4_v2": (0.5168, 0.8658),
    "Standard_D5_v2": (1.0336, 1.7316),
    "Standard_DS5_v2": (1.0336, 1.7316),
    "Standard_D11_v2": (0.1630, 0.2512),
    "Standard_DS11_v2": (0.1630, 0.2512),
    "Standard_D12_v2": (0.3260, 0.5024),
    "Standard_DS12_v2": (0.3260, 0.5024),
    "Standard_D13_v2": (0.6520, 1.0048),
    "Standard_DS13_v2": (0.6520, 1.0048),
    "Standard_D14_v2": (1.3040, 2.0096),
    "Standard_DS14_v2": (1.3040, 2.0096),
    "Standard_D2_v3": (0.0854, 0.1531),
    "Standard_D2s_v3": (0.0854, 0.1531),
    "Standard_D4_v3": (0.1708, 0.3063),
    "Standard_D4s_v3": (0.1708, 0.3063),
    "Standard_D8_v3": (0.3416, 0.6126),
    "Standard_D8s_v3": (0.3416, 0.6126),
    "Standard_D16_v3": (0.6832, 1.2252),
    "Standard_D16s_v3": (0.6832, 1.2252),
    "Standard_D32_v3": (1.3664, 2.4504),
    "Standard_D32s_v3": (1.3664, 2.4504),
    "Standard_D48_v3": (2.0496, 3.6756),
    "Standard_D48s_v3": (2.0496, 3.6756),
    "Standard_D64_v3": (2.7328, 4.9008),
    "Standard_D64s_v3": (2.7328, 4.9008),
    "Standard_E2_v3": (0.1147, 0.1823),
    "Standard_E2s_v3": (0.1147, 0.1823),
    "Standard_E4_v3": (0.2297, 0.3650),
    "Standard_E4s_v3": (0.2297, 0.3650),
    "Standard_E8_v3": (0.4594, 0.7300),
    "Standard_E8s_v3": (0.4594, 0.7300),
    "Standard_E16_v3": (0.9188, 1.4600),
    "Standard_E16s_v3": (0.9188, 1.4600),
    "Standard_E20_v3": (1.1485, 1.8250),
    "Standard_E20s_v3": (1.1485, 1.8250),
    "Standard_E32_v3": (1.8376, 2.9200),
    "Standard_E32s_v3": (1.8376, 2.9200),
    "Standard_E48_v3": (2.7564, 4.3800),
    "Standard_E48s_v3": (2.7564, 4.3800),
    "Standard_E64_v3": (3.6752, 5.8400),
    "Standard_E64s_v3": (3.6752, 5.8400),
    "Standard_E64i_v3": (3.6752, 5.8400),
    "Standard_E64is_v3": (3.6752, 5.8400),
    "Standard_F1": (0.0441, 0.0778),
    "Standard_F1s": (0.0441, 0.0778),
    "Standard_F2": (0.0882, 0.1557),
    "Standard_F2s": (0.0882, 0.1557),
    "Standard_F4": (0.1764, 0.3114),
    "Standard_F4s": (0.1764, 0.3114),
    "Standard_F8": (0.3528, 0.6228),
    "Standard_F8s": (0.3528, 0.6228),
    "Standard_F16": (0.7056, 1.2456),
    "Standard_F16s": (0.7056, 1.2456),
    "Standard_F2s_v2": (0.0744, 0.1417),
    "Standard_F4s_v2": (0.1487, 0.2834),
    "Standard_F8s_v2": (0.2974, 0.5668),
    "Standard_F16s_v2": (0.5948, 1.1336),
    "Standard_F32s_v2": (1.1896, 2.2672),
    "Standard_F48s_v2": (1.7844, 3.4008),
    "Standard_F64s_v2": (2.3792, 4.5344),
    "Standard_F72s_v2": (2.6766, 5.1012),
    "Standard_A1_v2": (0.0338, 0.0588),
    "Standard_A2_v2": (0.0705, 0.1234),
    "Standard_A4_v2": (0.1483, 0.2584),
    "Standard_A8_v2": (0.3113, 0.5404),
    "Standard_A2m_v2": (0.0991, 0.1520),
    "Standard_A4m_v2": (0.1982, 0.3040),
    "Standard_A8m_v2": (0.3965, 0.6080),
    "Standard_L4s": (0.2640, 0.4000),
    "Standard_L8s": (0.5280, 0.8000),
    "Standard_L16s": (1.0560, 1.6000),
    "Standard_L32s": (2.1120, 3.2000),
    "Standard_L8s_v2": (0.4960, 0.7680),
    "Standard_L16s_v2": (0.9920, 1.5360),
    "Standard_L32s_v2": (1.9840, 3.0720),
    "Standard_L48s_v2": (2.9760, 4.6080),
    "Standard_L64s_v2": (3.9680, 6.1440),
    "Standard_L80s_v2": (4.9600, 7.6800),
    # Target v5 & v6 SKUs (UK South GBP/hr: Linux, Windows)
    "Standard_B2ts_v2": (0.0084, 0.0144),
    "Standard_B2ls_v2": (0.0168, 0.0236),
    "Standard_B2s_v2": (0.0336, 0.0404),
    "Standard_B4s_v2": (0.0672, 0.0808),
    "Standard_B8s_v2": (0.1344, 0.1616),
    "Standard_B16s_v2": (0.2688, 0.3232),
    "Standard_B32s_v2": (0.5376, 0.6464),
    "Standard_D2s_v5": (0.0854, 0.1531),
    "Standard_D4s_v5": (0.1708, 0.3063),
    "Standard_D8s_v5": (0.3416, 0.6126),
    "Standard_D16s_v5": (0.6832, 1.2252),
    "Standard_D32s_v5": (1.3664, 2.4504),
    "Standard_D48s_v5": (2.0496, 3.6756),
    "Standard_D64s_v5": (2.7328, 4.9008),
    "Standard_D96s_v5": (4.0992, 7.3512),
    "Standard_D2ls_v5": (0.0724, 0.1402),
    "Standard_D4ls_v5": (0.1448, 0.2804),
    "Standard_D8ls_v5": (0.2896, 0.5608),
    "Standard_D16ls_v5": (0.5792, 1.1216),
    "Standard_D32ls_v5": (1.1584, 2.2432),
    "Standard_D48ls_v5": (1.7376, 3.3648),
    "Standard_D64ls_v5": (2.3168, 4.4864),
    "Standard_D96ls_v5": (3.4752, 6.7296),
    "Standard_D2s_v6": (0.0896, 0.1574),
    "Standard_D4s_v6": (0.1792, 0.3148),
    "Standard_D8s_v6": (0.3584, 0.6296),
    "Standard_D16s_v6": (0.7168, 1.2592),
    "Standard_D32s_v6": (1.4336, 2.5184),
    "Standard_D48s_v6": (2.1504, 3.7776),
    "Standard_D64s_v6": (2.8672, 5.0368),
    "Standard_D96s_v6": (4.3008, 7.5552),
    "Standard_D2ls_v6": (0.0756, 0.1434),
    "Standard_D4ls_v6": (0.1512, 0.2868),
    "Standard_D8ls_v6": (0.3024, 0.5736),
    "Standard_D16ls_v6": (0.6048, 1.1472),
    "Standard_D32ls_v6": (1.2096, 2.2944),
    "Standard_F2als_v6": (0.0756, 0.1434),
    "Standard_F4als_v6": (0.1512, 0.2868),
    "Standard_F8als_v6": (0.3024, 0.5736),
    "Standard_F16als_v6": (0.6048, 1.1472),
    "Standard_F32als_v6": (1.2096, 2.2944),
    "Standard_F48als_v6": (1.8144, 3.4416),
    "Standard_F64als_v6": (2.4192, 4.5888),
    "Standard_E2s_v5": (0.1147, 0.1823),
    "Standard_E4s_v5": (0.2297, 0.3650),
    "Standard_E8s_v5": (0.4594, 0.7300),
    "Standard_E16s_v5": (0.9188, 1.4600),
    "Standard_E20s_v5": (1.1485, 1.8250),
    "Standard_E32s_v5": (1.8376, 2.9200),
    "Standard_E48s_v5": (2.7564, 4.3800),
    "Standard_E64s_v5": (3.6752, 5.8400),
    "Standard_E96s_v5": (5.5128, 8.7600),
    "Standard_E2s_v6": (0.1204, 0.1882),
    "Standard_E4s_v6": (0.2408, 0.3764),
    "Standard_E8s_v6": (0.4816, 0.7528),
    "Standard_E16s_v6": (0.9632, 1.5056),
    "Standard_E20s_v6": (1.2040, 1.8820),
    "Standard_E32s_v6": (1.9264, 3.0112),
    "Standard_E48s_v6": (2.8896, 4.5168),
    "Standard_E64s_v6": (3.8528, 6.0224),
    "Standard_E96s_v6": (5.7792, 9.0336),
    "Standard_L8s_v3": (0.4640, 0.7360),
    "Standard_L16s_v3": (0.9280, 1.4720),
    "Standard_L32s_v3": (1.8560, 2.9440),
    "Standard_L48s_v3": (2.7840, 4.4160),
    "Standard_L64s_v3": (3.7120, 5.8880),
    "Standard_L80s_v3": (4.6400, 7.3600),
    "Standard_L8s_v4": (0.4760, 0.7480),
    "Standard_L16s_v4": (0.9520, 1.4960),
    "Standard_L32s_v4": (1.9040, 2.9920),
    "Standard_L48s_v4": (2.8560, 4.4880),
    "Standard_L64s_v4": (3.8080, 5.9840),
    "Standard_L80s_v4": (4.7600, 7.4800),
}

_REGION_MULTIPLIER: Dict[str, float] = {
    "uksouth": 1.00,
    "ukwest": 1.03,
    "westeurope": 1.02,
    "northeurope": 0.96,
    "francecentral": 1.02,
    "francesouth": 1.05,
    "norwayeast": 1.04,
    "norwaywest": 1.06,
    "eastus": 0.90,
    "eastus2": 0.90,
    "westus": 0.95,
    "westus2": 0.90,
    "southeastasia": 0.98,
}

_CURRENCY_FROM_GBP: Dict[str, float] = {
    "GBP": 1.0,
    "USD": 1.36215,
    "EUR": 1.175,
}


@dataclass(frozen=True)
class HikePolicy:
    name: str = POLICY_SERVICE_HEALTH
    v1_hike_pct: float = 25.0
    v2_hike_pct: float = 25.0
    v3_hike_pct: float = 0.0
    apply_regional_to_v3: bool = True

    @property
    def label(self) -> str:
        if self.name == POLICY_SERVICE_HEALTH:
            return (
                f"Service Health notices (EoL v1 +{self.v1_hike_pct:g}% & v2 +{self.v2_hike_pct:g}% global; "
                "non-EoL v2/v3 regional +8-17% in 7 regions, 0% in UK)"
            )
        if (
            self.v1_hike_pct == self.v2_hike_pct == self.v3_hike_pct
            and not self.apply_regional_to_v3
        ):
            return f"Legacy v1/v2/v3 hike (+{self.v1_hike_pct:g}% across v1, v2 and v3)"
        return (
            f"Custom hike (v1 +{self.v1_hike_pct:g}%, v2 +{self.v2_hike_pct:g}%, "
            f"v3 +{self.v3_hike_pct:g}%)"
        )

    def hike_pct_for(self, sku_info: SkuInfo, region: str) -> Tuple[float, str]:
        """Return ``(hike_percentage, reason)`` for a classified SKU and Azure region."""
        reg = (region or "").strip().lower()
        if self.name == POLICY_SERVICE_HEALTH:
            if sku_info.in_global_25_notice:
                pct = self.v1_hike_pct if sku_info.generation == GEN_V1 else self.v2_hike_pct
                return (
                    pct,
                    f"Global legacy {sku_info.generation} ({sku_info.series}) price hike "
                    f"(+{pct:g}% from 01/02/2027; exempt from regional hike)",
                )
            if reg in REGIONAL_FEB_2027_HIKES:
                pct = REGIONAL_FEB_2027_HIKES[reg]
                return pct, f"Regional {reg} price hike (+{pct:g}% from 01/02/2027)"
            if self.v3_hike_pct > 0 and sku_info.generation == GEN_V3:
                return self.v3_hike_pct, f"Configured v3 price hike (+{self.v3_hike_pct:g}% from 01/02/2027)"
            return (
                0.0,
                f"{sku_info.series} in {reg or 'unknown'}: not in global legacy +25% list and outside the "
                "7 regional-hike regions (0% list-price hike; v3 RI renewals ended 01/07/2026)",
            )

        if sku_info.generation == GEN_V1:
            return self.v1_hike_pct, f"Legacy v1 SKU price hike (+{self.v1_hike_pct:g}% from 01/02/2027)"
        if sku_info.generation == GEN_V2:
            return self.v2_hike_pct, f"Legacy v2 SKU price hike (+{self.v2_hike_pct:g}% from 01/02/2027)"
        if self.apply_regional_to_v3 and reg in REGIONAL_FEB_2027_HIKES and self.v3_hike_pct == 0:
            pct = REGIONAL_FEB_2027_HIKES[reg]
            return pct, f"Regional {reg} price hike (+{pct:g}% from 01/02/2027)"
        return self.v3_hike_pct, f"Legacy v3 SKU price hike (+{self.v3_hike_pct:g}% from 01/02/2027)"


@dataclass(frozen=True)
class PriceQuote:
    hourly_rate: float
    currency: str
    meter_name: str
    pricing_model: str
    source: str  # "retail-api" or "fallback-table"


@dataclass(frozen=True)
class TargetPriceQuote:
    sku: str
    payg_hourly_rate: float
    feb_payg_hourly_rate: float
    ri_3y_hourly_rate: float
    currency: str
    source: str  # "retail-api" or "fallback-table"


def uses_hybrid_benefit(os_type: str, license_type: str) -> bool:
    """True when Azure Hybrid Benefit (BYOL) waives the OS licence surcharge."""
    lic = (license_type or "").strip().upper()
    if lic in ("WINDOWS_SERVER", "WINDOWS_CLIENT", "RHEL_BYOS", "SLES_BYOS"):
        return True
    return False


def effective_os_meter(os_type: str, license_type: str) -> str:
    """Return 'Linux' (base compute rate) or 'Windows' (OS licence included)."""
    if uses_hybrid_benefit(os_type, license_type):
        return "Linux"
    if (os_type or "").strip().lower() == "windows":
        return "Windows"
    return "Linux"


class PricingClient:
    """Resolve hourly Pay-As-You-Go VM prices from the Azure Retail Prices API with an offline fallback."""

    def __init__(
        self,
        transport: Transport,
        *,
        currency: str = DEFAULT_CURRENCY,
        endpoint: str = RETAIL_PRICES_ENDPOINT,
        offline: bool = False,
        timeout: float = 20.0,
    ) -> None:
        self._transport = transport
        self.currency = (currency or DEFAULT_CURRENCY).strip().upper()
        self._endpoint = endpoint.rstrip("/")
        self._offline = offline
        self._timeout = timeout
        self._cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self.api_failures = 0

    def quote(
        self,
        sku_info: SkuInfo,
        region: str,
        *,
        os_type: str = "Linux",
        license_type: str = "",
        priority: str = "Regular",
    ) -> PriceQuote:
        reg = (region or "uksouth").strip().lower()
        ahb = uses_hybrid_benefit(os_type, license_type)
        meter_os = effective_os_meter(os_type, license_type)
        prio = (priority or "Regular").strip().lower()
        model_label = (
            f"{os_type or 'Linux'} (AHB/BYOL base rate)"
            if ahb
            else f"{os_type or 'Linux'} ({'Spot' if prio == 'spot' else ('Low Priority' if prio == 'low' else 'PAYG')})"
        )

        if not self._offline:
            for candidate_sku in dict.fromkeys((sku_info.sku, sku_info.parent_sku)):
                items = self._fetch_items(reg, candidate_sku)
                matched = _select_meter(items, meter_os=meter_os, priority=prio)
                if matched is not None:
                    rate, meter_name, cur = matched
                    return PriceQuote(
                        hourly_rate=rate,
                        currency=cur,
                        meter_name=meter_name,
                        pricing_model=model_label,
                        source="retail-api",
                    )

        rate = _fallback_hourly_rate(sku_info, reg, meter_os=meter_os, priority=prio, currency=self.currency)
        return PriceQuote(
            hourly_rate=rate,
            currency=self.currency,
            meter_name=f"{sku_info.parent_sku} ({meter_os})",
            pricing_model=model_label,
            source="fallback-table",
        )

    def quote_target_sku(
        self,
        arm_sku: str,
        fallback_vcpus: int,
        region: str,
        *,
        os_type: str = "Linux",
        license_type: str = "",
        priority: str = "Regular",
    ) -> TargetPriceQuote:
        """Quote PAYG, Feb 2027 PAYG, and 3-Year RI hourly rates for a target modern SKU (v5/v6/v7)."""
        reg = (region or "uksouth").strip().lower()
        meter_os = effective_os_meter(os_type, license_type)
        prio = (priority or "Regular").strip().lower()
        sku_clean = (arm_sku or "Standard_D2s_v5").strip()

        payg_rate: Optional[float] = None
        linux_rate: Optional[float] = None
        cur = self.currency
        source = "fallback-table"

        if not self._offline and sku_clean:
            items = self._fetch_items(reg, sku_clean)
            matched = _select_meter(items, meter_os=meter_os, priority=prio)
            if matched is not None:
                payg_rate, _, cur = matched
                linux_matched = _select_meter(items, meter_os="Linux", priority=prio)
                linux_rate = linux_matched[0] if linux_matched is not None else payg_rate
                source = "retail-api"

        if payg_rate is None:
            payg_rate = _fallback_arm_sku_rate(
                sku_clean, fallback_vcpus, reg, meter_os=meter_os, priority=prio, currency=self.currency
            )
            linux_rate = _fallback_arm_sku_rate(
                sku_clean, fallback_vcpus, reg, meter_os="Linux", priority=prio, currency=self.currency
            )

        assert linux_rate is not None
        reg_pct = 0.0 if "_v7" in sku_clean.lower() else REGIONAL_FEB_2027_HIKES.get(reg, 0.0)
        mult = 1.0 + (reg_pct / 100.0)
        feb_payg = round(payg_rate * mult, 4)
        feb_linux = linux_rate * mult
        if prio in ("spot", "low"):
            ri_3y = feb_payg
        else:
            os_surcharge = max(0.0, feb_payg - feb_linux)
            ri_3y = round((feb_linux * 0.42) + os_surcharge, 4)

        return TargetPriceQuote(
            sku=sku_clean,
            payg_hourly_rate=payg_rate,
            feb_payg_hourly_rate=feb_payg,
            ri_3y_hourly_rate=ri_3y,
            currency=cur,
            source=source,
        )

    def _fetch_items(self, region: str, arm_sku: str) -> List[Dict[str, Any]]:
        key = (region, arm_sku.lower())
        with self._lock:
            if key in self._cache:
                return self._cache[key]

        odata_filter = (
            f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}' "
            f"and armSkuName eq '{arm_sku}' and priceType eq 'Consumption'"
        )
        query = urllib.parse.urlencode({"currencyCode": self.currency, "$filter": odata_filter})
        url = f"{self._endpoint}?{query}"
        items: List[Dict[str, Any]] = []
        try:
            response = self._transport.request("GET", url, {"Accept": "application/json"}, None, self._timeout)
            if 200 <= response.status < 300:
                payload = json.loads(response.body.decode("utf-8-sig"))
                raw_items = payload.get("Items") if isinstance(payload, dict) else None
                if isinstance(raw_items, list):
                    items = [item for item in raw_items if isinstance(item, dict)]
            else:
                self.api_failures += 1
        except (TransportError, ValueError, UnicodeDecodeError) as exc:
            log.debug("Retail Prices API lookup failed for %s in %s: %s", arm_sku, region, exc)
            self.api_failures += 1

        with self._lock:
            self._cache[key] = items
        return items


def _select_meter(
    items: List[Dict[str, Any]], *, meter_os: str, priority: str
) -> Optional[Tuple[float, str, str]]:
    """Pick the matching Consumption retail price from Azure Retail Prices API items."""
    want_windows = meter_os == "Windows"
    want_spot = priority == "spot"
    want_low = priority == "low"

    candidates: List[Tuple[int, str, float, str, str]] = []
    for item in items:
        if str(item.get("type") or "") != "Consumption":
            continue
        product = str(item.get("productName") or "")
        if "Cloud Services" in product or "Dedicated Host" in product:
            continue
        sku_name = str(item.get("skuName") or "")
        meter_name = str(item.get("meterName") or sku_name)
        is_windows = "windows" in product.lower()
        if is_windows != want_windows:
            continue
        combined = f"{sku_name} {meter_name}".lower()
        is_spot = "spot" in combined
        is_low = "low priority" in combined
        if want_spot != is_spot or want_low != is_low:
            continue
        try:
            price = float(item.get("retailPrice"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        # Prefer primary/non-promo meters and the most recent effectiveStartDate
        is_promo = 1 if "promo" in combined else 0
        start_date = str(item.get("effectiveStartDate") or "")
        currency = str(item.get("currencyCode") or DEFAULT_CURRENCY).upper()
        candidates.append((is_promo, start_date, price, meter_name, currency))

    if not candidates:
        return None
    # Sort by non-promo first, then latest effectiveStartDate
    candidates.sort(key=lambda entry: (entry[0], -int(entry[1][:4]) if entry[1][:4].isdigit() else 0))
    _, _, price, meter_name, currency = candidates[0]
    return price, meter_name, currency


def _fallback_hourly_rate(
    sku_info: SkuInfo,
    region: str,
    *,
    meter_os: str,
    priority: str,
    currency: str,
) -> float:
    want_windows = meter_os == "Windows"
    exact = _EXACT_UKS_GBP.get(sku_info.parent_sku) or _EXACT_UKS_GBP.get(sku_info.sku)
    if exact is not None:
        base_gbp = exact[1] if want_windows else exact[0]
    else:
        per_vcpu = _SERIES_PER_VCPU_GBP.get(sku_info.series, (0.0550, 0.0890))
        rate_per_vcpu = per_vcpu[1] if want_windows else per_vcpu[0]
        base_gbp = rate_per_vcpu * max(1, sku_info.vcpus)

    reg_mult = _REGION_MULTIPLIER.get(region, 1.0)
    cur_mult = _CURRENCY_FROM_GBP.get(currency.upper(), 1.0)
    prio_mult = 0.25 if priority == "spot" else (0.30 if priority == "low" else 1.0)
    return round(base_gbp * reg_mult * cur_mult * prio_mult, 4)


def _fallback_arm_sku_rate(
    arm_sku: str,
    fallback_vcpus: int,
    region: str,
    *,
    meter_os: str,
    priority: str,
    currency: str,
) -> float:
    want_windows = meter_os == "Windows"
    exact = _EXACT_UKS_GBP.get(arm_sku)
    if exact is not None:
        base_gbp = exact[1] if want_windows else exact[0]
    else:
        up = arm_sku.upper()
        if "LS_V5" in up:
            per_vcpu = _SERIES_PER_VCPU_GBP["Dlsv5"]
        elif "LS_V6" in up or "ALS_V6" in up:
            per_vcpu = _SERIES_PER_VCPU_GBP["Falsv6"]
        elif "_V6" in up and "_E" in up:
            per_vcpu = _SERIES_PER_VCPU_GBP["Esv6"]
        elif "_V5" in up and "_E" in up:
            per_vcpu = _SERIES_PER_VCPU_GBP["Esv5"]
        elif "_V6" in up:
            per_vcpu = _SERIES_PER_VCPU_GBP["Dsv6"]
        elif "BS_V2" in up or "_B" in up:
            per_vcpu = _SERIES_PER_VCPU_GBP["Bsv2"]
        elif "LS_V4" in up:
            per_vcpu = _SERIES_PER_VCPU_GBP["Lsv4"]
        elif "LS_V3" in up:
            per_vcpu = _SERIES_PER_VCPU_GBP["Lsv3"]
        else:
            per_vcpu = _SERIES_PER_VCPU_GBP["Dsv5"]
        rate_per_vcpu = per_vcpu[1] if want_windows else per_vcpu[0]
        base_gbp = rate_per_vcpu * max(2, fallback_vcpus)

    reg_mult = _REGION_MULTIPLIER.get(region, 1.0)
    cur_mult = _CURRENCY_FROM_GBP.get(currency.upper(), 1.0)
    prio_mult = 0.25 if priority == "spot" else (0.30 if priority == "low" else 1.0)
    return round(base_gbp * reg_mult * cur_mult * prio_mult, 4)

