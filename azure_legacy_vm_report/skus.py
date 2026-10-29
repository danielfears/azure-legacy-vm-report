"""Classify Azure Virtual Machine SKUs into v1, v2 and v3 legacy generations and retirement metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

GEN_V1 = "v1"
GEN_V2 = "v2"
GEN_V3 = "v3"
LEGACY_GENERATIONS = (GEN_V1, GEN_V2, GEN_V3)

STAGE_EOL = "End of Life"
STAGE_RETIRED = "Retired"
STAGE_EXTENDED = "Extended"

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


def classify_vm_sku(raw_sku: str) -> Optional[SkuInfo]:
    """Return legacy ``SkuInfo`` if ``raw_sku`` is a v1, v2 or v3 Azure VM SKU, else ``None``."""
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
        if gen_num not in (1, 2, 3):
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

    # Generic fallback for any other _v1, _v2 or _v3 SKU
    vcpus, active = _extract_vcpus(up, "")
    prefix_match = re.match(r"^([A-Za-z]+)", body)
    fam = (prefix_match.group(1) if prefix_match else "VM") + gen
    return SkuInfo(
        sku=canonical,
        parent_sku=parent,
        generation=gen,
        series=fam,
        category="General purpose",
        vcpus=vcpus,
        active_vcpus=active,
        lifecycle_stage=STAGE_EOL if gen in (GEN_V1, GEN_V2) else STAGE_EXTENDED,
        retirement_date="15/11/2028" if gen in (GEN_V1, GEN_V2) else "15/11/2029",
        recommended_v5="Dsv5 / Esv5",
        recommended_current="Dsv6 / Esv6",
        disk_controller_note="Verify Gen2, NVMe and MANA prerequisites before resizing",
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
