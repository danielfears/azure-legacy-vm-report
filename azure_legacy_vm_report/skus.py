"""Classify Azure Virtual Machine SKUs into v1, v2 and v3 legacy generations and retirement metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

GEN_V1 = "v1"
GEN_V2 = "v2"
GEN_V3 = "v3"
GEN_V4 = "v4"
GEN_V5 = "v5"
GEN_V6 = "v6"
LEGACY_GENERATIONS = (GEN_V1, GEN_V2, GEN_V3)
EXTENDED_GENERATIONS = (GEN_V1, GEN_V2, GEN_V3, GEN_V4, GEN_V5, GEN_V6)

STAGE_EOL = "End of Life"
STAGE_RETIRED = "Retired"
STAGE_EXTENDED = "Extended"
STAGE_CURRENT = "Current"

_CLASSIC_A_VCPUS: Dict[str, int] = {
    "EXTRASMALL": 1,
    "SMALL": 1,
    "MEDIUM": 2,
    "LARGE": 4,
    "EXTRALARGE": 8,
    "A0": 1,
    "A1": 1,
    "A2": 2,
    "A3": 4,
    "A4": 8,
    "A5": 2,
    "A6": 4,
    "A7": 8,
    "A8": 8,
    "A9": 16,
    "A10": 8,
    "A11": 16,
}

# D1-D5 and DS1-DS5 v1/v2 use size numbers 1..5 for 1, 2, 4, 8, 16 vCPUs;
# D11-D15 and DS11-DS15 v1/v2 use 11..15 for 2, 4, 8, 16, 20 vCPUs.
_D_V1_V2_VCPUS: Dict[int, int] = {
    1: 1,
    2: 2,
    3: 4,
    4: 8,
    5: 16,
    11: 2,
    12: 4,
    13: 8,
    14: 16,
    15: 20,
}

# G1-G5 and GS1-GS5 use 1..5 for 2, 4, 8, 16, 32 vCPUs.
_G_V1_VCPUS: Dict[int, int] = {
    1: 2,
    2: 4,
    3: 8,
    4: 16,
    5: 32,
}

_ExplicitV = re.compile(r"^(?:Standard_|Basic_)?(?P<body>.+?)_v(?P<gen>\d+)$", re.IGNORECASE)
_BSeriesV1 = re.compile(r"^B(?P<num>\d+)(?P<subletter>ls|ms|s)$", re.IGNORECASE)
_DSeriesV1 = re.compile(r"^D(?P<s_flag>S)?(?P<num>\d+)(?:-(?P<active>\d+))?$", re.IGNORECASE)
_FSeriesV1 = re.compile(r"^F(?P<num>\d+)(?P<s_flag>S)?$", re.IGNORECASE)
_GSeriesV1 = re.compile(r"^G(?P<s_flag>S)?(?P<num>[1-5])(?:-(?P<active>\d+))?$", re.IGNORECASE)
_LSeriesV1 = re.compile(r"^L(?P<num>\d+)S$", re.IGNORECASE)
_ASeriesV1 = re.compile(r"^A(?P<num>0|[1-9]|10|11)$", re.IGNORECASE)
_NPSeriesV1 = re.compile(r"^NP(?P<num>10|20|40)S$", re.IGNORECASE)
_HCSeriesV1 = re.compile(r"^HC(?P<num>44)(?:-(?P<active>\d+))?RS$", re.IGNORECASE)
_HBSeriesV1 = re.compile(r"^HB(?P<num>60)(?:-(?P<active>\d+))?RS$", re.IGNORECASE)
_HSeriesV1 = re.compile(r"^H(?P<num>8|16)M?R?$", re.IGNORECASE)
_MSeriesV1 = re.compile(r"^M(?P<num>\d+)(?:-(?P<active>\d+))?(?:[A-Z]*)$", re.IGNORECASE)
_NSeriesV1 = re.compile(r"^(?P<fam>NC|ND|NV)(?P<num>\d+)(?:R|RS|S)?$", re.IGNORECASE)
_DCSeriesV1 = re.compile(r"^DC(?P<num>\d+)S$", re.IGNORECASE)


_STD_D_VCPUS = (2, 4, 8, 16, 32, 48, 64, 96)
_STD_E_VCPUS = (2, 4, 8, 16, 20, 32, 48, 64, 96)
_STD_L_VCPUS = (8, 16, 32, 48, 64, 80)
_STD_B_VCPUS = (2, 4, 8, 16, 32)


def _snap_size(vcpus: int, allowed: Tuple[int, ...]) -> int:
    for val in allowed:
        if val >= vcpus:
            return val
    return allowed[-1]


def _resolve_concrete_targets(sku: str, series: str, vcpus: int) -> Tuple[str, str, str]:
    """Return ``(target_v5_sku, target_current_sku, target_quota_family)`` for a legacy SKU."""
    up_sku = (sku or "").upper()
    ser = (series or "").strip()
    d_n = _snap_size(max(2, vcpus), _STD_D_VCPUS)
    e_n = _snap_size(max(2, vcpus), _STD_E_VCPUS)
    l_n = _snap_size(max(8, vcpus), _STD_L_VCPUS)
    b_n = _snap_size(max(2, vcpus), _STD_B_VCPUS)

    if ser in ("Bv1", "Bsv2", "Basv2", "Bpsv2"):
        if "B1LS" in up_sku:
            v5_sku = "Standard_B2ts_v2"
        elif "B1S" in up_sku or "B2S" in up_sku:
            v5_sku = "Standard_B2ls_v2"
        else:
            v5_sku = f"Standard_B{b_n}s_v2"
        return v5_sku, f"Standard_D{d_n}ls_v6", "standardBSv2Family"

    if ser in ("Av1", "Basic_A", "Av2"):
        if vcpus <= 2:
            return "Standard_B2s_v2", "Standard_D2ls_v6", "standardBSv2Family"
        return f"Standard_D{d_n}ls_v5", f"Standard_D{d_n}ls_v6", "standardDlsv5Family"

    if ser in ("Amv2", "Ev3", "Esv3", "G", "Gs", "Ev4", "Esv4"):
        return f"Standard_E{e_n}s_v5", f"Standard_E{e_n}s_v6", "standardESv5Family"

    if ser in ("F", "Fs", "Fsv2"):
        return f"Standard_D{d_n}ls_v5", f"Standard_F{d_n}als_v6", "standardDlsv5Family"

    if ser in ("Ls", "Lsv1", "Lsv2", "Lsv3", "Lasv3"):
        return f"Standard_L{l_n}s_v3", f"Standard_L{l_n}s_v4", "standardLsv3Family"

    if ser in ("DCs", "DCsv2", "DCsv3", "DCdsv3"):
        return f"Standard_DC{d_n}as_v5", f"Standard_DC{d_n}as_v6", "standardDCasv5Family"

    if ser in ("HB", "HBv2", "HC", "H"):
        return "Standard_HB120rs_v3", "Standard_HB176rs_v4", "standardHBv3Family"

    if ser in ("M", "Msv2/Mdsv2"):
        m_n = _snap_size(max(32, vcpus), (32, 64, 128, 192))
        return f"Standard_M{m_n}s_v2", f"Standard_M{m_n}s_v3", "standardMSv2Family"

    if ser in ("NP", "NVv3", "NCv3", "NCasT4_v3", "NC", "ND", "NV"):
        return "Standard_NV36ads_A10_v5", "Standard_NC24ads_A100_v4", "standardNVadsA10v5Family"

    return f"Standard_D{d_n}s_v5", f"Standard_D{d_n}s_v6", "standardDSv5Family"


def _is_ri_purchase_blocked(generation: str, series: str, in_global_25_notice: bool) -> bool:
    """True when Microsoft ended new 1Y/3Y RI purchases & renewals on 01/07/2026."""
    if in_global_25_notice or generation == GEN_V1:
        return True
    if series in ("Dv3", "Dsv3", "Ev3", "Esv3", "DCsv3", "DCdsv3", "NVv3", "NCv3"):
        return True
    return False


@dataclass(frozen=True)
class SkuInfo:
    sku: str
    parent_sku: str
    generation: str
    series: str
    category: str
    vcpus: int
    active_vcpus: int
    lifecycle_stage: str
    retirement_date: str
    recommended_v5: str
    recommended_current: str
    disk_controller_note: str
    in_global_25_notice: bool
    target_v5_sku: str = ""
    target_current_sku: str = ""
    target_quota_family: str = ""
    ri_purchase_blocked: bool = False

    def __post_init__(self) -> None:
        v5_sku, cur_sku, q_fam = _resolve_concrete_targets(self.sku, self.series, self.vcpus)
        if not self.target_v5_sku:
            object.__setattr__(self, "target_v5_sku", v5_sku)
        if not self.target_current_sku:
            object.__setattr__(self, "target_current_sku", cur_sku)
        if not self.target_quota_family:
            object.__setattr__(self, "target_quota_family", q_fam)
        if not self.ri_purchase_blocked:
            object.__setattr__(
                self,
                "ri_purchase_blocked",
                _is_ri_purchase_blocked(self.generation, self.series, self.in_global_25_notice),
            )


_SkuBodyParts = re.compile(
    r"^(?P<fam>[A-Za-z]+)(?P<nums>\d+(?:-\d+)?)(?P<mods>[A-Za-z]*)(?P<mid>(?:_[A-Za-z0-9]+)*?)(?P<ver>_v\d+)?$",
    re.IGNORECASE,
)


def _canonicalise_sku_body(body_raw: str) -> str:
    """Normalise SKU casing so e.g. 'D8S_v3' and 'D8s_v3' both become 'D8s_v3'."""
    m = _SkuBodyParts.match(body_raw.strip())
    if not m:
        return body_raw.strip()
    fam = m.group("fam").upper()
    nums = m.group("nums")
    mods = m.group("mods").lower()
    mid = m.group("mid") or ""
    ver = (m.group("ver") or "").lower()
    return f"{fam}{nums}{mods}{mid}{ver}"


def parent_unconstrained_sku(sku: str) -> str:
    """Return the parent full-core SKU for a constrained-core SKU (e.g. Standard_E16-4s_v3 -> Standard_E16s_v3)."""
    return re.sub(r"(\d+)-\d+", r"\1", sku)


def classify_vm_sku(raw_sku: str, *, include_modern_regional: bool = False) -> Optional[SkuInfo]:
    """Return ``SkuInfo`` if ``raw_sku`` is a v1, v2 or v3 Azure VM SKU (or v4-v6 when ``include_modern_regional`` is set)."""
    text = (raw_sku or "").strip()
    if not text:
        return None

    upper = text.upper()
    if upper in ("EXTRASMALL", "SMALL", "MEDIUM", "LARGE", "EXTRALARGE"):
        vcpus = _CLASSIC_A_VCPUS[upper]
        return SkuInfo(
            sku=text,
            parent_sku=text,
            generation=GEN_V1,
            series="Av1",
            category="General purpose",
            vcpus=vcpus,
            active_vcpus=vcpus,
            lifecycle_stage=STAGE_RETIRED,
            retirement_date="31/08/2024",
            recommended_v5="Bsv2 / Dsv5",
            recommended_current="Dsv6 / Dasv6",
            disk_controller_note="Gen1 SCSI -> Gen2 NVMe rebuild required for v6/v7",
            in_global_25_notice=True,
        )

    is_basic = upper.startswith("BASIC_")
    if upper.startswith("STANDARD_"):
        body_raw = _canonicalise_sku_body(text[9:])
        canonical = "Standard_" + body_raw
    elif is_basic:
        body_raw = _canonicalise_sku_body(text[6:])
        canonical = "Basic_" + body_raw
    else:
        body_raw = _canonicalise_sku_body(text)
        canonical = "Standard_" + body_raw

    match_v = _ExplicitV.match(canonical)
    if match_v:
        gen_num = int(match_v.group("gen"))
        allowed_nums = (1, 2, 3, 4, 5, 6) if include_modern_regional else (1, 2, 3)
        if gen_num not in allowed_nums:
            return None
        gen = f"v{gen_num}"
        body = match_v.group("body")
        return _classify_versioned(canonical, body, gen)

    return _classify_unversioned_v1(canonical, body_raw, is_basic=is_basic)


def _extract_vcpus(body: str, series_prefix: str) -> Tuple[int, int]:
    """Extract (billed_vcpus, active_vcpus) from a versioned SKU body such as 'D16-4s' or 'DS14-4'."""
    match = re.search(r"(?P<num>\d+)(?:-(?P<active>\d+))?", body)
    if not match:
        return 2, 2
    num = int(match.group("num"))
    active = int(match.group("active")) if match.group("active") else num
    if series_prefix in ("D", "DS") and num in _D_V1_V2_VCPUS:
        billed = _D_V1_V2_VCPUS[num]
        return billed, min(active, billed) if match.group("active") else billed
    return num, active


def _classify_versioned(canonical: str, body: str, gen: str) -> SkuInfo:
    up = body.upper()
    parent = parent_unconstrained_sku(canonical)

    if gen == GEN_V1:
        if up.startswith("DS"):
            vcpus, active = _extract_vcpus(up, "DS")
            return _build_d_v1_v2(canonical, parent, GEN_V1, "Dsv1", vcpus, active)
        if up.startswith("D"):
            vcpus, active = _extract_vcpus(up, "D")
            return _build_d_v1_v2(canonical, parent, GEN_V1, "Dv1", vcpus, active)
        if up.startswith("B"):
            vcpus, active = _extract_vcpus(up, "B")
            return _build_b_v1(canonical, parent, vcpus, active)
        if up.startswith("LS") or up.startswith("L"):
            vcpus, active = _extract_vcpus(up, "L")
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V1,
                series="Lsv1",
                category="Storage optimised",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EOL,
                retirement_date="01/05/2028",
                recommended_v5="Lsv3 / Lasv3",
                recommended_current="Lsv4 / Lasv4",
                disk_controller_note="Lsv3/v4 support SCSI and NVMe; local storage uses NVMe",
                in_global_25_notice=True,
            )

    if gen == GEN_V2:
        if up.startswith("A"):
            vcpus, active = _extract_vcpus(up, "A")
            is_m = "M" in up
            series = "Amv2" if is_m else "Av2"
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V2,
                series=series,
                category="General purpose",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EOL,
                retirement_date="15/11/2028",
                recommended_v5="Bsv2 / Basv2 / Dsv5 / Dasv5",
                recommended_current="Dsv6 / Dasv6",
                disk_controller_note="v5/Bsv2 keep SCSI; v6 requires Gen2 + NVMe + MANA",
                in_global_25_notice=True,
            )
        if up.startswith("DS") or (up.startswith("D") and "S" in up):
            vcpus, active = _extract_vcpus(up, "DS")
            return _build_d_v1_v2(canonical, parent, GEN_V2, "Dsv2", vcpus, active)
        if up.startswith("D") and not up.startswith("DC"):
            vcpus, active = _extract_vcpus(up, "D")
            return _build_d_v1_v2(canonical, parent, GEN_V2, "Dv2", vcpus, active)
        if up.startswith("F"):
            vcpus, active = _extract_vcpus(up, "F")
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V2,
                series="Fsv2",
                category="Compute optimised",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EOL,
                retirement_date="15/11/2028",
                recommended_v5="Dlsv5 / Dldsv5 / Dsv5",
                recommended_current="Falsv6 / Dlsv6 / Dldsv6",
                disk_controller_note="v5 keeps SCSI; v6 requires Gen2 + NVMe + MANA",
                in_global_25_notice=True,
            )
        if up.startswith("L"):
            vcpus, active = _extract_vcpus(up, "L")
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V2,
                series="Lsv2",
                category="Storage optimised",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EOL,
                retirement_date="15/11/2028",
                recommended_v5="Lsv3 / Lasv3",
                recommended_current="Lsv4 / Lasv4",
                disk_controller_note="Lsv3/v4 support SCSI and NVMe; local disk is NVMe",
                in_global_25_notice=True,
            )
        if up.startswith("B"):
            vcpus, active = _extract_vcpus(up, "B")
            series = "Basv2" if "A" in up else ("Bpsv2" if "P" in up else "Bsv2")
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V2,
                series=series,
                category="General purpose",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EXTENDED,
                retirement_date="Not announced",
                recommended_v5="Bsv2 / Basv2 (current B-family)",
                recommended_current="Dsv6 / Dasv6",
                disk_controller_note="Bsv2/Basv2 use SCSI; v6 requires Gen2 + NVMe",
                in_global_25_notice=False,
            )
        if up.startswith("DC"):
            vcpus, active = _extract_vcpus(up, "DC")
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V2,
                series="DCsv2",
                category="Confidential compute",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_RETIRED,
                retirement_date="30/06/2026",
                recommended_v5="DCsv3 / DCdsv3",
                recommended_current="DCasv5 / DCadsv5",
                disk_controller_note="Retired SGX series; migrate to DCv5 confidential VMs",
                in_global_25_notice=True,
            )
        if up.startswith("HB"):
            vcpus, active = _extract_vcpus(up, "HB")
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V2,
                series="HBv2",
                category="HPC",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EOL,
                retirement_date="31/05/2027",
                recommended_v5="HBv3 / HBv4",
                recommended_current="HBv5 / HX",
                disk_controller_note="Retires 31/05/2027; validate MPI and InfiniBand NDR/HDR",
                in_global_25_notice=True,
            )
        if up.startswith("M"):
            vcpus, active = _extract_vcpus(up, "M")
            is_192 = "192" in up
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V2,
                series="Msv2/Mdsv2",
                category="Memory optimised",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EOL if is_192 else STAGE_EXTENDED,
                retirement_date="31/03/2027" if is_192 else "Not announced",
                recommended_v5="Msv2 / Mdsv2 (non-isolated)",
                recommended_current="Msv3 / Mdsv3 / Mbdsv3",
                disk_controller_note="M192i*v2 isolated sizes retire 31/03/2027; Mv3 uses Gen2/NVMe",
                in_global_25_notice=is_192,
            )

    if gen == GEN_V3:
        if up.startswith("D") and not up.startswith("DC"):
            vcpus, active = _extract_vcpus(up, "D3")
            has_s = "S" in up
            series = "Dsv3" if has_s else "Dv3"
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V3,
                series=series,
                category="General purpose",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EOL,
                retirement_date="15/11/2029",
                recommended_v5="Dsv5 / Ddsv5 / Dasv5 / Dadsv5",
                recommended_current="Dsv6 / Ddsv6 / Dasv6 / Dadsv7",
                disk_controller_note="v5 keeps SCSI (requires AccelNet); v6/v7 require Gen2 + NVMe + MANA",
                in_global_25_notice=False,
            )
        if up.startswith("E"):
            vcpus, active = _extract_vcpus(up, "E3")
            has_s = "S" in up
            series = "Esv3" if has_s else "Ev3"
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V3,
                series=series,
                category="Memory optimised",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EOL,
                retirement_date="15/11/2029",
                recommended_v5="Esv5 / Edsv5 / Easv5 / Eadsv5",
                recommended_current="Esv6 / Edsv6 / Easv6 / Easv7",
                disk_controller_note="v5 keeps SCSI (requires AccelNet); v6/v7 require Gen2 + NVMe + MANA",
                in_global_25_notice=False,
            )
        if up.startswith("DC"):
            vcpus, active = _extract_vcpus(up, "DC")
            series = "DCdsv3" if "D" in up[2:] else "DCsv3"
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V3,
                series=series,
                category="Confidential compute",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EOL,
                retirement_date="31/10/2029",
                recommended_v5="DCasv5 / DCadsv5",
                recommended_current="DCasv6 / DCadsv6",
                disk_controller_note="SGX DCsv3/DCdsv3 retires 31/10/2029",
                in_global_25_notice=False,
            )
        if up.startswith("L"):
            vcpus, active = _extract_vcpus(up, "L")
            series = "Lasv3" if "A" in up else "Lsv3"
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V3,
                series=series,
                category="Storage optimised",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EXTENDED,
                retirement_date="Not announced",
                recommended_v5="Lsv3 / Lasv3",
                recommended_current="Lsv4 / Lasv4",
                disk_controller_note="Supports SCSI and NVMe",
                in_global_25_notice=False,
            )
        if up.startswith("NV"):
            vcpus, active = _extract_vcpus(up, "NV")
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V3,
                series="NVv3",
                category="GPU accelerated",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_RETIRED,
                retirement_date="30/09/2026",
                recommended_v5="NVadsA10_v5 / NVads_V710_v5",
                recommended_current="NVadsA10_v5 / NCasT4_v3",
                disk_controller_note="NVv3 retired 30/09/2026",
                in_global_25_notice=False,
            )
        if up.startswith("NC"):
            vcpus, active = _extract_vcpus(up, "NC")
            is_t4 = "T4" in up
            return SkuInfo(
                sku=canonical,
                parent_sku=parent,
                generation=GEN_V3,
                series="NCasT4_v3" if is_t4 else "NCv3",
                category="GPU accelerated",
                vcpus=vcpus,
                active_vcpus=active,
                lifecycle_stage=STAGE_EXTENDED if is_t4 else STAGE_RETIRED,
                retirement_date="Not announced" if is_t4 else "30/09/2025",
                recommended_v5="NCads_H100_v5 / NVadsA10_v5",
                recommended_current="NCads_H100_v5 / NCv6",
                disk_controller_note="Validate CUDA/GPU driver compatibility",
                in_global_25_notice=False,
            )

    # Generic fallback for any other _v1.._v6 SKU
    vcpus, active = _extract_vcpus(up, "")
    prefix_match = re.match(r"^([A-Za-z]+)", body)
    fam_prefix = (prefix_match.group(1) if prefix_match else "VM").upper()
    has_s = "S" in up[len(fam_prefix):]
    fam = f"{fam_prefix}{'s' if has_s else ''}{gen}"
    is_modern = gen in (GEN_V4, GEN_V5, GEN_V6)
    category = "Memory optimised" if fam_prefix.startswith("E") else (
        "Compute optimised" if fam_prefix.startswith("F") else (
            "Storage optimised" if fam_prefix.startswith("L") else "General purpose"
        )
    )
    return SkuInfo(
        sku=canonical,
        parent_sku=parent,
        generation=gen,
        series=fam,
        category=category,
        vcpus=vcpus,
        active_vcpus=active,
        lifecycle_stage=(
            STAGE_CURRENT if gen in (GEN_V5, GEN_V6)
            else (STAGE_EXTENDED if gen in (GEN_V3, GEN_V4) else STAGE_EOL)
        ),
        retirement_date=(
            "Not announced" if is_modern
            else ("15/11/2028" if gen in (GEN_V1, GEN_V2) else "15/11/2029")
        ),
        recommended_v5="Esv5 / Edsv5" if fam_prefix.startswith("E") else "Dsv5 / Ddsv5",
        recommended_current="Esv6 / Edsv6" if fam_prefix.startswith("E") else "Dsv6 / Ddsv6",
        disk_controller_note=(
            "Current-generation SKU (exposed to regional hike in 7 EU/APAC regions)"
            if is_modern
            else "Verify Gen2, NVMe and MANA prerequisites before resizing"
        ),
        in_global_25_notice=gen in (GEN_V1, GEN_V2),
    )


def _classify_unversioned_v1(canonical: str, body: str, *, is_basic: bool = False) -> Optional[SkuInfo]:
    up = body.upper()
    parent = parent_unconstrained_sku(canonical)

    m_a = _ASeriesV1.match(up)
    if m_a:
        vcpus = _CLASSIC_A_VCPUS.get(up, 1)
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series="Basic_A" if is_basic else "Av1",
            category="General purpose",
            vcpus=vcpus,
            active_vcpus=vcpus,
            lifecycle_stage=STAGE_RETIRED,
            retirement_date="31/08/2024",
            recommended_v5="Bsv2 / Dsv5",
            recommended_current="Dsv6 / Dasv6",
            disk_controller_note="Av1 retired; migrate to Bsv2 or Dsv5/v6",
            in_global_25_notice=True,
        )

    m_b = _BSeriesV1.match(up)
    if m_b:
        num = int(m_b.group("num"))
        return _build_b_v1(canonical, parent, num, num)

    m_d = _DSeriesV1.match(up)
    if m_d:
        num = int(m_d.group("num"))
        if num in _D_V1_V2_VCPUS:
            vcpus = _D_V1_V2_VCPUS[num]
            active = int(m_d.group("active")) if m_d.group("active") else vcpus
            series = "Ds" if m_d.group("s_flag") else "D"
            return _build_d_v1_v2(canonical, parent, GEN_V1, series, vcpus, active)

    m_f = _FSeriesV1.match(up)
    if m_f:
        vcpus = int(m_f.group("num"))
        series = "Fs" if m_f.group("s_flag") else "F"
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series=series,
            category="Compute optimised",
            vcpus=vcpus,
            active_vcpus=vcpus,
            lifecycle_stage=STAGE_EOL,
            retirement_date="15/11/2028",
            recommended_v5="Dlsv5 / Dldsv5 / Dsv5",
            recommended_current="Falsv6 / Dlsv6 / Dldsv6",
            disk_controller_note="v5 keeps SCSI; v6 requires Gen2 + NVMe + MANA",
            in_global_25_notice=True,
        )

    m_g = _GSeriesV1.match(up)
    if m_g:
        num = int(m_g.group("num"))
        vcpus = _G_V1_VCPUS[num]
        active = int(m_g.group("active")) if m_g.group("active") else vcpus
        series = "Gs" if m_g.group("s_flag") else "G"
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series=series,
            category="Memory optimised",
            vcpus=vcpus,
            active_vcpus=active,
            lifecycle_stage=STAGE_EOL,
            retirement_date="15/11/2028",
            recommended_v5="Esv5 / Edsv5 / Lsv3",
            recommended_current="Esv6 / Edsv6 / Lsv4",
            disk_controller_note="v5/Lsv3 support SCSI; v6 requires Gen2 + NVMe + MANA",
            in_global_25_notice=True,
        )

    m_l = _LSeriesV1.match(up)
    if m_l:
        vcpus = int(m_l.group("num"))
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series="Ls",
            category="Storage optimised",
            vcpus=vcpus,
            active_vcpus=vcpus,
            lifecycle_stage=STAGE_EOL,
            retirement_date="01/05/2028",
            recommended_v5="Lsv3 / Lasv3",
            recommended_current="Lsv4 / Lasv4",
            disk_controller_note="Lsv3/v4 support SCSI and NVMe; local disk is NVMe",
            in_global_25_notice=True,
        )

    m_np = _NPSeriesV1.match(up)
    if m_np:
        vcpus = int(m_np.group("num"))
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series="NP",
            category="FPGA accelerated",
            vcpus=vcpus,
            active_vcpus=vcpus,
            lifecycle_stage=STAGE_EOL,
            retirement_date="31/05/2027",
            recommended_v5="NCads_H100_v5 / NDv2",
            recommended_current="NCads_H100_v5 / NCasT4_v3",
            disk_controller_note="FPGA NP-series retires 31/05/2027; requires porting from XRT/Vitis to GPU/CUDA",
            in_global_25_notice=True,
        )

    m_hc = _HCSeriesV1.match(up)
    if m_hc:
        vcpus = int(m_hc.group("num"))
        active = int(m_hc.group("active")) if m_hc.group("active") else vcpus
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series="HC",
            category="HPC",
            vcpus=vcpus,
            active_vcpus=active,
            lifecycle_stage=STAGE_EOL,
            retirement_date="31/05/2027",
            recommended_v5="HBv4 / HBv3 / Ddsv5",
            recommended_current="HBv5 / HX / Ddsv6",
            disk_controller_note="HC-series retires 31/05/2027",
            in_global_25_notice=True,
        )

    m_hb = _HBSeriesV1.match(up)
    if m_hb:
        vcpus = int(m_hb.group("num"))
        active = int(m_hb.group("active")) if m_hb.group("active") else vcpus
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series="HB",
            category="HPC",
            vcpus=vcpus,
            active_vcpus=active,
            lifecycle_stage=STAGE_RETIRED,
            retirement_date="31/08/2024",
            recommended_v5="HBv4 / HBv3",
            recommended_current="HBv5 / HX",
            disk_controller_note="HB v1 retired; move to HBv4/HBv5",
            in_global_25_notice=True,
        )

    m_h = _HSeriesV1.match(up)
    if m_h:
        vcpus = int(m_h.group("num"))
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series="H",
            category="HPC",
            vcpus=vcpus,
            active_vcpus=vcpus,
            lifecycle_stage=STAGE_RETIRED,
            retirement_date="31/08/2024",
            recommended_v5="HBv4 / HBv3",
            recommended_current="HBv5 / HX",
            disk_controller_note="H-series retired; move to HBv4/HBv5",
            in_global_25_notice=True,
        )

    m_m = _MSeriesV1.match(up)
    if m_m:
        vcpus = int(m_m.group("num"))
        active = int(m_m.group("active")) if m_m.group("active") else vcpus
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series="M",
            category="Memory optimised",
            vcpus=vcpus,
            active_vcpus=active,
            lifecycle_stage=STAGE_EXTENDED,
            retirement_date="Not announced",
            recommended_v5="Msv2 / Mdsv2",
            recommended_current="Msv3 / Mdsv3 / Mbdsv3",
            disk_controller_note="Mv1 uses SCSI; Mv3 requires Gen2 + NVMe + MANA",
            in_global_25_notice=False,
        )

    m_n = _NSeriesV1.match(up)
    if m_n:
        vcpus = int(m_n.group("num"))
        fam = m_n.group("fam").upper()
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series=fam,
            category="GPU accelerated",
            vcpus=vcpus,
            active_vcpus=vcpus,
            lifecycle_stage=STAGE_RETIRED,
            retirement_date="30/09/2023",
            recommended_v5="NVadsA10_v5 / NCads_H100_v5",
            recommended_current="NCv6 / NVadsA10_v5",
            disk_controller_note="Legacy v1 GPU series retired",
            in_global_25_notice=True,
        )

    m_dc = _DCSeriesV1.match(up)
    if m_dc:
        vcpus = int(m_dc.group("num"))
        return SkuInfo(
            sku=canonical,
            parent_sku=parent,
            generation=GEN_V1,
            series="DCs",
            category="Confidential compute",
            vcpus=vcpus,
            active_vcpus=vcpus,
            lifecycle_stage=STAGE_RETIRED,
            retirement_date="30/06/2026",
            recommended_v5="DCsv3 / DCdsv3",
            recommended_current="DCasv5 / DCadsv5",
            disk_controller_note="Legacy SGX series retired",
            in_global_25_notice=True,
        )

    return None


def _build_b_v1(canonical: str, parent: str, vcpus: int, active: int) -> SkuInfo:
    return SkuInfo(
        sku=canonical,
        parent_sku=parent,
        generation=GEN_V1,
        series="Bv1",
        category="General purpose",
        vcpus=vcpus,
        active_vcpus=active,
        lifecycle_stage=STAGE_EOL,
        retirement_date="15/11/2028",
        recommended_v5="Bsv2 / Basv2 / Dlsv5 / Dalsv5",
        recommended_current="Dlsv6 / Dalsv6",
        disk_controller_note="Bsv2/Basv2 keep SCSI (note: Bsv2/Basv2 not in sovereign clouds); v6 requires Gen2 + NVMe",
        in_global_25_notice=True,
    )


def _build_d_v1_v2(canonical: str, parent: str, gen: str, series: str, vcpus: int, active: int) -> SkuInfo:
    retire = "15/11/2028" if series in ("Dv1", "Dsv1") else "01/05/2028"
    return SkuInfo(
        sku=canonical,
        parent_sku=parent,
        generation=gen,
        series=series,
        category="General purpose",
        vcpus=vcpus,
        active_vcpus=active,
        lifecycle_stage=STAGE_EOL,
        retirement_date=retire,
        recommended_v5="Dsv5 / Ddsv5 / Dasv5 / Dadsv5",
        recommended_current="Dsv6 / Ddsv6 / Dasv6 / Dadsv7",
        disk_controller_note="v5 keeps SCSI (enable AccelNet before resize); v6/v7 require Gen2 + NVMe + MANA",
        in_global_25_notice=True,
    )
