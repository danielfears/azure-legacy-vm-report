"""Data model for legacy (v1, v2, v3) Azure Virtual Machine inventory and February 2027 cost projections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .costmgmt import (
    ActualVmUsage,
    AdvisorRightSizeInfo,
    VmScheduleInfo,
)
from .pricing import (
    DEFAULT_HOURS_PER_MONTH,
    REGIONAL_FEB_2027_HIKES,
    HikePolicy,
    PriceQuote,
    TargetPriceQuote,
)
from .skus import SkuInfo

WAVE_1_RESIZE = "Wave 1: Drop-in v5 Resize (SCSI)"
WAVE_2_POOL = "Wave 2: Managed Pool Replace (AKS/PaaS)"
WAVE_3_REBUILD = "Wave 3: Gen2 / NVMe or Specialised Rebuild"

TYPE_VM = "VirtualMachine"
TYPE_VMSS = "VirtualMachineScaleSet"

POWER_RUNNING = "Running"
POWER_STOPPED = "Stopped (allocated)"
POWER_DEALLOCATED = "Deallocated"
POWER_UNKNOWN = "Unknown"

COST_SOURCE_AUTO = "auto"
COST_SOURCE_LAST_MONTH = "last-month"
COST_SOURCE_MTD = "mtd"
COST_SOURCE_RETAIL = "retail"
VALID_COST_SOURCES = (COST_SOURCE_AUTO, COST_SOURCE_LAST_MONTH, COST_SOURCE_MTD, COST_SOURCE_RETAIL)



def normalise_power_state(raw_code: Any, *, capacity: Optional[int] = None) -> str:
    """Turn an Azure instanceView powerState code into a clear status label."""
    if capacity is not None and capacity == 0:
        return POWER_DEALLOCATED
    text = str(raw_code or "").strip().lower()
    if not text:
        return POWER_RUNNING if capacity and capacity > 0 else POWER_UNKNOWN
    if "deallocat" in text:
        return POWER_DEALLOCATED
    if "running" in text or "starting" in text:
        return POWER_RUNNING
    if "stopped" in text or "stopping" in text:
        return POWER_STOPPED
    return POWER_UNKNOWN


def is_power_state_billed(power_state: str) -> bool:
    """True when Azure bills compute for this power state (Stopped without deallocating is still billed)."""
    return power_state != POWER_DEALLOCATED


def normalise_os_type(raw_os: Any, raw_license: Any = "") -> str:
    text = str(raw_os or "").strip().lower()
    lic = str(raw_license or "").strip().lower()
    if "win" in text or "win" in lic:
        return "Windows"
    return "Linux"


def normalise_priority(raw_priority: Any) -> str:
    text = str(raw_priority or "").strip().lower()
    if text == "spot":
        return "Spot"
    if text in ("low", "lowpriority"):
        return "Low"
    return "Regular"


@dataclass(frozen=True)
class LegacyVmRecord:
    resource_id: str
    name: str
    resource_type: str
    deployment_kind: str
    tenant_id: str
    tenant_name: str
    subscription_id: str
    subscription_name: str
    resource_group: str
    region: str
    sku: str
    generation: str
    series: str
    category: str
    instance_count: int
    vcpus_per_instance: int
    total_vcpus: int
    os_type: str
    license_type: str
    hybrid_benefit: bool
    priority: str
    power_state: str
    is_billed_now: bool
    hourly_rate: float
    currency: str
    pricing_model: str
    price_source: str
    hours_per_month: float
    inferred_hours_per_month: float
    provisioned_current_monthly: float
    retail_active_monthly: float
    schedule_adjusted_monthly: float
    actual_last_month_cost: Optional[float]
    actual_last_month_hours: Optional[float]
    actual_mtd_cost: Optional[float]
    actual_mtd_extrapolated_cost: Optional[float]
    actual_mtd_hours: Optional[float]
    auto_shutdown_schedule: str
    cost_basis_used: str
    current_monthly: float
    hike_pct: float
    hike_reason: str
    feb_hourly_rate: float
    provisioned_feb_monthly: float
    feb_monthly: float
    monthly_delta: float
    annual_delta: float
    provisioned_monthly_delta: float
    legacy_25_hike_pct: float
    service_health_hike_pct: float
    lifecycle_stage: str
    retirement_date: str
    recommended_v5: str
    recommended_current: str
    disk_controller_note: str
    management_group: str = "Tenant Root"
    cost_allocation_tag: str = "Untagged"
    target_v5_sku: str = ""
    target_v5_hourly_rate: float = 0.0
    target_v5_monthly: float = 0.0
    target_v5_savings_vs_feb: float = 0.0
    target_v5_3yr_ri_monthly: float = 0.0
    target_current_sku: str = ""
    target_current_hourly_rate: float = 0.0
    target_current_monthly: float = 0.0
    target_current_savings_vs_feb: float = 0.0
    target_current_3yr_ri_monthly: float = 0.0
    ri_status: str = ""
    ri_expiry_date: str = ""
    advisor_recommendation: str = ""
    advisor_monthly_saving: float = 0.0
    quota_status: str = ""
    migration_wave: str = ""
    migration_cli_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "name": self.name,
            "resource_type": self.resource_type,
            "deployment_kind": self.deployment_kind,
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "subscription_id": self.subscription_id,
            "subscription_name": self.subscription_name,
            "management_group": self.management_group,
            "cost_allocation_tag": self.cost_allocation_tag,
            "resource_group": self.resource_group,
            "region": self.region,
            "sku": self.sku,
            "generation": self.generation,
            "series": self.series,
            "category": self.category,
            "instance_count": self.instance_count,
            "vcpus_per_instance": self.vcpus_per_instance,
            "total_vcpus": self.total_vcpus,
            "os_type": self.os_type,
            "license_type": self.license_type,
            "hybrid_benefit": self.hybrid_benefit,
            "priority": self.priority,
            "power_state": self.power_state,
            "is_billed_now": self.is_billed_now,
            "auto_shutdown_schedule": self.auto_shutdown_schedule,
            "hourly_rate": round(self.hourly_rate, 4),
            "currency": self.currency,
            "pricing_model": self.pricing_model,
            "price_source": self.price_source,
            "cost_basis_used": self.cost_basis_used,
            "hours_per_month": self.hours_per_month,
            "inferred_hours_per_month": round(self.inferred_hours_per_month, 1),
            "provisioned_current_monthly": round(self.provisioned_current_monthly, 2),
            "retail_active_monthly": round(self.retail_active_monthly, 2),
            "schedule_adjusted_monthly": round(self.schedule_adjusted_monthly, 2),
            "actual_last_month_cost": (
                round(self.actual_last_month_cost, 2) if self.actual_last_month_cost is not None else None
            ),
            "actual_last_month_hours": (
                round(self.actual_last_month_hours, 1) if self.actual_last_month_hours is not None else None
            ),
            "actual_mtd_cost": (
                round(self.actual_mtd_cost, 2) if self.actual_mtd_cost is not None else None
            ),
            "actual_mtd_extrapolated_cost": (
                round(self.actual_mtd_extrapolated_cost, 2)
                if self.actual_mtd_extrapolated_cost is not None
                else None
            ),
            "actual_mtd_hours": (
                round(self.actual_mtd_hours, 1) if self.actual_mtd_hours is not None else None
            ),
            "current_monthly": round(self.current_monthly, 2),
            "hike_pct": round(self.hike_pct, 2),
            "hike_reason": self.hike_reason,
            "feb_hourly_rate": round(self.feb_hourly_rate, 4),
            "provisioned_feb_monthly": round(self.provisioned_feb_monthly, 2),
            "feb_monthly": round(self.feb_monthly, 2),
            "monthly_delta": round(self.monthly_delta, 2),
            "annual_delta": round(self.annual_delta, 2),
            "provisioned_monthly_delta": round(self.provisioned_monthly_delta, 2),
            "legacy_25_hike_pct": round(self.legacy_25_hike_pct, 2),
            "service_health_hike_pct": round(self.service_health_hike_pct, 2),
            "lifecycle_stage": self.lifecycle_stage,
            "retirement_date": self.retirement_date,
            "recommended_v5": self.recommended_v5,
            "recommended_current": self.recommended_current,
            "target_v5_sku": self.target_v5_sku,
            "target_v5_hourly_rate": round(self.target_v5_hourly_rate, 4),
            "target_v5_monthly": round(self.target_v5_monthly, 2),
            "target_v5_savings_vs_feb": round(self.target_v5_savings_vs_feb, 2),
            "target_v5_3yr_ri_monthly": round(self.target_v5_3yr_ri_monthly, 2),
            "target_current_sku": self.target_current_sku,
            "target_current_hourly_rate": round(self.target_current_hourly_rate, 4),
            "target_current_monthly": round(self.target_current_monthly, 2),
            "target_current_savings_vs_feb": round(self.target_current_savings_vs_feb, 2),
            "target_current_3yr_ri_monthly": round(self.target_current_3yr_ri_monthly, 2),
            "ri_status": self.ri_status,
            "ri_expiry_date": self.ri_expiry_date,
            "advisor_recommendation": self.advisor_recommendation,
            "advisor_monthly_saving": round(self.advisor_monthly_saving, 2),
            "quota_status": self.quota_status,
            "migration_wave": self.migration_wave,
            "migration_cli_hint": self.migration_cli_hint,
            "disk_controller_note": self.disk_controller_note,
        }


def _format_schedule(sched: Optional[VmScheduleInfo]) -> str:
    if sched is None or not sched.status:
        return ""
    if sched.daily_time:
        return f"{sched.status} ({sched.daily_time})"
    return sched.status


def classify_migration_wave(
    *,
    deployment_kind: str,
    resource_type: str,
    name: str,
    resource_group: str,
    sku_info: SkuInfo,
) -> Tuple[str, str]:
    """Return ``(migration_wave, migration_cli_hint)`` for a legacy deployment."""
    kind = (deployment_kind or "").strip()
    rg = (resource_group or "<rg>").strip()
    rname = (name or "<name>").strip()
    v5_sku = sku_info.target_v5_sku or "Standard_D2s_v5"
    cur_sku = sku_info.target_current_sku or "Standard_D2s_v6"

    if sku_info.series in ("NP", "HC", "HB", "HBv2", "H", "NC", "ND", "NV", "NVv3", "NCv3", "DCs", "DCsv2", "Av1", "Basic_A"):
        return (
            WAVE_3_REBUILD,
            f"Rebuild on Gen2 image (NVMe + MANA) targeting {cur_sku} or {v5_sku}",
        )

    if (
        "AKS Node Pool" in kind
        or kind in ("Databricks Node", "OpenShift / ARO Node", "Batch Pool", "ML Compute", "Ephemeral / CI Job VM")
    ):
        if "AKS Node Pool" in kind:
            cluster_hint = "<cluster>"
            if "(" in kind and "/" in kind:
                cluster_hint = kind.split("(", 1)[1].split("/", 1)[0].strip()
            return (
                WAVE_2_POOL,
                f"az aks nodepool add --cluster-name {cluster_hint} -g {rg} -n v5pool --node-vm-size {v5_sku}",
            )
        return (
            WAVE_2_POOL,
            f"Rolling-replace managed pool nodes onto {v5_sku} (or Gen2/NVMe {cur_sku})",
        )

    if resource_type == TYPE_VMSS:
        return (
            WAVE_1_RESIZE,
            f"az vmss update -g {rg} -n {rname} --set sku.name={v5_sku}",
        )

    return (
        WAVE_1_RESIZE,
        f"az vm resize -g {rg} -n {rname} --size {v5_sku}",
    )


def build_legacy_record(
    *,
    resource_id: str,
    name: str,
    resource_type: str,
    tenant_id: str,
    tenant_name: str,
    subscription_id: str,
    subscription_name: str,
    resource_group: str,
    region: str,
    sku_info: SkuInfo,
    instance_count: int,
    os_type: str,
    license_type: str,
    priority: str,
    power_state: str,
    quote: PriceQuote,
    policy: HikePolicy,
    hours_per_month: float = DEFAULT_HOURS_PER_MONTH,
    include_deallocated_cost: bool = False,
    cost_source: str = COST_SOURCE_AUTO,
    actual_usage: Optional[ActualVmUsage] = None,
    schedule_info: Optional[VmScheduleInfo] = None,
    deployment_kind: str = "",
    schedule_summary: str = "",
    inferred_hours_per_month: Optional[float] = None,
    target_v5_quote: Optional[TargetPriceQuote] = None,
    target_current_quote: Optional[TargetPriceQuote] = None,
    management_group: str = "Tenant Root",
    cost_allocation_tag: str = "Untagged",
    ri_status: str = "",
    ri_expiry_date: str = "",
    advisor_info: Optional[AdvisorRightSizeInfo] = None,
    quota_status: str = "",
) -> LegacyVmRecord:
    billed_now = is_power_state_billed(power_state) and instance_count > 0
    active_for_cost = billed_now or (include_deallocated_cost and instance_count > 0)

    eff_inferred_hours = hours_per_month if inferred_hours_per_month is None else inferred_hours_per_month
    prov_current = round(quote.hourly_rate * hours_per_month * max(0, instance_count), 2)
    retail_active = prov_current if active_for_cost else 0.0
    sched_active = (
        round(quote.hourly_rate * eff_inferred_hours * max(0, instance_count), 2)
        if active_for_cost
        else 0.0
    )

    has_cm = actual_usage is not None and actual_usage.has_data
    last_mo_cost = round(actual_usage.last_month_cost, 2) if has_cm and actual_usage else None
    last_mo_hrs = round(actual_usage.last_month_hours, 1) if has_cm and actual_usage else None
    mtd_cost = round(actual_usage.mtd_cost, 2) if has_cm and actual_usage else None
    mtd_ext_cost = round(actual_usage.mtd_extrapolated_cost, 2) if has_cm and actual_usage else None
    mtd_hrs = round(actual_usage.mtd_hours, 1) if has_cm and actual_usage else None

    if cost_source == COST_SOURCE_RETAIL:
        current_mo = retail_active
        basis_used = "retail-730h"
    elif not has_cm:
        current_mo = sched_active
        basis_used = "retail-scheduled" if eff_inferred_hours != hours_per_month else "retail-730h"
    elif cost_source == COST_SOURCE_LAST_MONTH:
        current_mo = last_mo_cost if last_mo_cost is not None else sched_active
        basis_used = "last-month-actual"
    elif cost_source == COST_SOURCE_MTD:
        current_mo = mtd_ext_cost if mtd_ext_cost is not None else sched_active
        basis_used = "mtd-extrapolated"
    else:  # COST_SOURCE_AUTO
        if last_mo_cost is not None and last_mo_cost > 0:
            current_mo = last_mo_cost
            basis_used = "last-month-actual"
        elif mtd_ext_cost is not None and mtd_ext_cost > 0:
            current_mo = mtd_ext_cost
            basis_used = "mtd-extrapolated"
        elif last_mo_cost is not None:
            current_mo = prov_current if (include_deallocated_cost and instance_count > 0) else 0.0
            basis_used = "last-month-actual"
        else:
            current_mo = sched_active
            basis_used = "retail-scheduled" if eff_inferred_hours != hours_per_month else "retail-730h"

    hike_pct, hike_reason = policy.hike_pct_for(sku_info, region)
    multiplier = 1.0 + (hike_pct / 100.0)
    feb_hourly = round(quote.hourly_rate * multiplier, 4)
    prov_feb = round(prov_current * multiplier, 2)
    feb_mo = round(current_mo * multiplier, 2)
    mo_delta = round(feb_mo - current_mo, 2)
    yr_delta = round(mo_delta * 12.0, 2)
    prov_delta = round(prov_feb - prov_current, 2)

    # Calculate post-migration target running costs (preserving actual duty cycle & negotiated discount ratio)
    base_hr = quote.hourly_rate if quote.hourly_rate > 0 else 1.0
    v5_sku = target_v5_quote.sku if target_v5_quote else sku_info.target_v5_sku
    v5_hr = target_v5_quote.feb_payg_hourly_rate if target_v5_quote else quote.hourly_rate
    v5_ri_hr = target_v5_quote.ri_3y_hourly_rate if target_v5_quote else round(v5_hr * 0.55, 4)
    v5_mo = round(current_mo * (v5_hr / base_hr), 2) if quote.hourly_rate > 0 else current_mo
    v5_save_feb = round(feb_mo - v5_mo, 2)
    v5_ri_mo = round(current_mo * (v5_ri_hr / base_hr), 2) if quote.hourly_rate > 0 else round(v5_mo * 0.55, 2)

    cur_sku = target_current_quote.sku if target_current_quote else sku_info.target_current_sku
    cur_hr = target_current_quote.feb_payg_hourly_rate if target_current_quote else round(v5_hr * 1.04, 4)
    cur_ri_hr = target_current_quote.ri_3y_hourly_rate if target_current_quote else round(cur_hr * 0.55, 4)
    cur_mo = round(current_mo * (cur_hr / base_hr), 2) if quote.hourly_rate > 0 else current_mo
    cur_save_feb = round(feb_mo - cur_mo, 2)
    cur_ri_mo = round(current_mo * (cur_ri_hr / base_hr), 2) if quote.hourly_rate > 0 else round(cur_mo * 0.55, 2)

    reg_norm = (region or "").strip().lower()
    sh_pct = (
        25.0
        if sku_info.in_global_25_notice
        else REGIONAL_FEB_2027_HIKES.get(reg_norm, 0.0)
    )
    lic_upper = (license_type or "").strip().upper()
    ahb = lic_upper in ("WINDOWS_SERVER", "WINDOWS_CLIENT", "RHEL_BYOS", "SLES_BYOS")
    kind_label = deployment_kind or ("VM Scale Set" if resource_type == TYPE_VMSS else "Standalone VM")
    sched_label = schedule_summary or _format_schedule(schedule_info)
    wave_label, cli_hint = classify_migration_wave(
        deployment_kind=kind_label,
        resource_type=resource_type,
        name=name,
        resource_group=resource_group,
        sku_info=sku_info,
    )
    eff_ri_status = ri_status or (
        "No RI (RI renewal blocked 01/07/2026)" if sku_info.ri_purchase_blocked else "No RI (PAYG / SP)"
    )
    adv_text = advisor_info.summary if advisor_info else ""
    adv_save = advisor_info.estimated_monthly_saving if advisor_info else 0.0

    return LegacyVmRecord(
        resource_id=resource_id,
        name=name,
        resource_type=resource_type,
        deployment_kind=kind_label,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        subscription_id=subscription_id,
        subscription_name=subscription_name or subscription_id,
        resource_group=resource_group,
        region=reg_norm or "unknown",
        sku=sku_info.sku,
        generation=sku_info.generation,
        series=sku_info.series,
        category=sku_info.category,
        instance_count=max(0, instance_count),
        vcpus_per_instance=sku_info.vcpus,
        total_vcpus=sku_info.vcpus * max(0, instance_count),
        os_type=os_type,
        license_type=license_type or "",
        hybrid_benefit=ahb,
        priority=priority,
        power_state=power_state,
        is_billed_now=billed_now,
        hourly_rate=quote.hourly_rate,
        currency=quote.currency,
        pricing_model=quote.pricing_model,
        price_source=quote.source,
        hours_per_month=hours_per_month,
        inferred_hours_per_month=eff_inferred_hours,
        provisioned_current_monthly=prov_current,
        retail_active_monthly=retail_active,
        schedule_adjusted_monthly=sched_active,
        actual_last_month_cost=last_mo_cost,
        actual_last_month_hours=last_mo_hrs,
        actual_mtd_cost=mtd_cost,
        actual_mtd_extrapolated_cost=mtd_ext_cost,
        actual_mtd_hours=mtd_hrs,
        auto_shutdown_schedule=sched_label,
        cost_basis_used=basis_used,
        current_monthly=current_mo,
        hike_pct=hike_pct,
        hike_reason=hike_reason,
        feb_hourly_rate=feb_hourly,
        provisioned_feb_monthly=prov_feb,
        feb_monthly=feb_mo,
        monthly_delta=mo_delta,
        annual_delta=yr_delta,
        provisioned_monthly_delta=prov_delta,
        legacy_25_hike_pct=25.0,
        service_health_hike_pct=sh_pct,
        lifecycle_stage=sku_info.lifecycle_stage,
        retirement_date=sku_info.retirement_date,
        recommended_v5=sku_info.recommended_v5,
        recommended_current=sku_info.recommended_current,
        disk_controller_note=sku_info.disk_controller_note,
        management_group=management_group or "Tenant Root",
        cost_allocation_tag=cost_allocation_tag or "Untagged",
        target_v5_sku=v5_sku,
        target_v5_hourly_rate=v5_hr,
        target_v5_monthly=v5_mo,
        target_v5_savings_vs_feb=v5_save_feb,
        target_v5_3yr_ri_monthly=v5_ri_mo,
        target_current_sku=cur_sku,
        target_current_hourly_rate=cur_hr,
        target_current_monthly=cur_mo,
        target_current_savings_vs_feb=cur_save_feb,
        target_current_3yr_ri_monthly=cur_ri_mo,
        ri_status=eff_ri_status,
        ri_expiry_date=ri_expiry_date,
        advisor_recommendation=adv_text,
        advisor_monthly_saving=adv_save,
        quota_status=quota_status,
        migration_wave=wave_label,
        migration_cli_hint=cli_hint,
    )


@dataclass
class NameMaps:
    tenant_name: str = ""
    default_domain: str = ""
    subscriptions: Dict[str, str] = field(default_factory=dict)

    def subscription_label(self, sub_id: str) -> str:
        key = (sub_id or "").strip().lower()
        return self.subscriptions.get(key) or sub_id
