"""Aggregate legacy VM records by generation (v1, v2, v3), SKU, subscription and tenant."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .collect import FETCH_OK, Issue, TenantData
from .dates import iso_utc
from .model import (
    COST_SOURCE_AUTO,
    COST_SOURCE_LAST_MONTH,
    COST_SOURCE_MTD,
    COST_SOURCE_RETAIL,
    POWER_DEALLOCATED,
    TYPE_VMSS,
    LegacyVmRecord,
)
from .pricing import HikePolicy
from .skus import LEGACY_GENERATIONS


@dataclass
class GenerationSummary:
    generation: str
    resource_count: int = 0
    instance_count: int = 0
    running_instances: int = 0
    deallocated_instances: int = 0
    total_vcpus: int = 0
    current_monthly: float = 0.0
    feb_monthly: float = 0.0
    monthly_delta: float = 0.0
    annual_delta: float = 0.0
    provisioned_current_monthly: float = 0.0
    provisioned_feb_monthly: float = 0.0
    provisioned_monthly_delta: float = 0.0
    legacy_25_feb_monthly: float = 0.0
    service_health_feb_monthly: float = 0.0

    @property
    def effective_hike_pct(self) -> float:
        if self.current_monthly <= 0:
            if self.provisioned_current_monthly > 0:
                return round((self.provisioned_monthly_delta / self.provisioned_current_monthly) * 100.0, 2)
            return 0.0
        return round((self.monthly_delta / self.current_monthly) * 100.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generation": self.generation,
            "resource_count": self.resource_count,
            "instance_count": self.instance_count,
            "running_instances": self.running_instances,
            "deallocated_instances": self.deallocated_instances,
            "total_vcpus": self.total_vcpus,
            "current_monthly": round(self.current_monthly, 2),
            "feb_monthly": round(self.feb_monthly, 2),
            "monthly_delta": round(self.monthly_delta, 2),
            "annual_delta": round(self.annual_delta, 2),
            "effective_hike_pct": self.effective_hike_pct,
            "provisioned_current_monthly": round(self.provisioned_current_monthly, 2),
            "provisioned_feb_monthly": round(self.provisioned_feb_monthly, 2),
            "provisioned_monthly_delta": round(self.provisioned_monthly_delta, 2),
            "legacy_25_feb_monthly": round(self.legacy_25_feb_monthly, 2),
            "service_health_feb_monthly": round(self.service_health_feb_monthly, 2),
        }


@dataclass
class SkuBreakdownRow:
    sku: str
    generation: str
    series: str
    category: str
    vcpus_per_instance: int
    resource_count: int = 0
    instance_count: int = 0
    running_instances: int = 0
    deallocated_instances: int = 0
    linux_instances: int = 0
    windows_instances: int = 0
    ahb_instances: int = 0
    regions: List[str] = field(default_factory=list)
    current_monthly: float = 0.0
    feb_monthly: float = 0.0
    monthly_delta: float = 0.0
    annual_delta: float = 0.0
    provisioned_current_monthly: float = 0.0
    provisioned_feb_monthly: float = 0.0
    hike_pct: float = 0.0
    retirement_date: str = ""
    recommended_v5: str = ""
    recommended_current: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sku": self.sku,
            "generation": self.generation,
            "series": self.series,
            "category": self.category,
            "vcpus_per_instance": self.vcpus_per_instance,
            "resource_count": self.resource_count,
            "instance_count": self.instance_count,
            "running_instances": self.running_instances,
            "deallocated_instances": self.deallocated_instances,
            "linux_instances": self.linux_instances,
            "windows_instances": self.windows_instances,
            "ahb_instances": self.ahb_instances,
            "regions": self.regions,
            "current_monthly": round(self.current_monthly, 2),
            "feb_monthly": round(self.feb_monthly, 2),
            "monthly_delta": round(self.monthly_delta, 2),
            "annual_delta": round(self.annual_delta, 2),
            "provisioned_current_monthly": round(self.provisioned_current_monthly, 2),
            "provisioned_feb_monthly": round(self.provisioned_feb_monthly, 2),
            "hike_pct": round(self.hike_pct, 2),
            "retirement_date": self.retirement_date,
            "recommended_v5": self.recommended_v5,
            "recommended_current": self.recommended_current,
        }


@dataclass
class SubscriptionBreakdownRow:
    subscription_id: str
    subscription_name: str
    v1_instances: int = 0
    v2_instances: int = 0
    v3_instances: int = 0
    total_instances: int = 0
    total_vcpus: int = 0
    current_monthly: float = 0.0
    feb_monthly: float = 0.0
    monthly_delta: float = 0.0
    annual_delta: float = 0.0
    provisioned_current_monthly: float = 0.0
    provisioned_feb_monthly: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "subscription_name": self.subscription_name,
            "v1_instances": self.v1_instances,
            "v2_instances": self.v2_instances,
            "v3_instances": self.v3_instances,
            "total_instances": self.total_instances,
            "total_vcpus": self.total_vcpus,
            "current_monthly": round(self.current_monthly, 2),
            "feb_monthly": round(self.feb_monthly, 2),
            "monthly_delta": round(self.monthly_delta, 2),
            "annual_delta": round(self.annual_delta, 2),
            "provisioned_current_monthly": round(self.provisioned_current_monthly, 2),
            "provisioned_feb_monthly": round(self.provisioned_feb_monthly, 2),
        }


@dataclass
class TenantReport:
    data: TenantData
    by_generation: Dict[str, GenerationSummary]
    total_summary: GenerationSummary
    sku_rows: List[SkuBreakdownRow]
    subscription_rows: List[SubscriptionBreakdownRow]

    @property
    def tenant_id(self) -> str:
        return self.data.spec.tenant_id

    @property
    def display_name(self) -> str:
        return self.data.display_name or self.tenant_id

    @property
    def default_domain(self) -> str:
        return self.data.default_domain

    @property
    def fetched(self) -> bool:
        return self.data.fetch_status == FETCH_OK and not self.data.fatal

    @property
    def fatal(self) -> bool:
        return self.data.fatal

    @property
    def records(self) -> List[LegacyVmRecord]:
        return self.data.records

    @property
    def issues(self) -> List[Issue]:
        return self.data.issues

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "default_domain": self.default_domain,
            "fetched": self.fetched,
            "discovery_method": self.data.discovery_method,
            "subscription_count": self.data.subscription_count,
            "total_resources_scanned": self.data.total_resources_scanned,
            "total_instances_scanned": self.data.total_instances_scanned,
            "modern_resources_skipped": self.data.modern_resources_skipped,
            "cost_management_subs_queried": self.data.cost_management_subs_queried,
            "cost_management_subs_succeeded": self.data.cost_management_subs_succeeded,
            "last_month_label": self.data.last_month_label,
            "current_month_label": self.data.current_month_label,
            "by_generation": {gen: self.by_generation[gen].to_dict() for gen in self.by_generation},
            "total": self.total_summary.to_dict(),
            "skus": [row.to_dict() for row in self.sku_rows],
            "subscriptions": [row.to_dict() for row in self.subscription_rows],
            "vms": [rec.to_dict() for rec in self.records],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class Report:
    version: str
    generated_at: datetime
    tz: tzinfo
    tz_name: str
    currency: str
    hours_per_month: float
    policy: HikePolicy
    generations: Tuple[str, ...]
    include_vmss: bool
    include_deallocated_cost: bool
    tenants: List[TenantReport]
    cost_source: str = COST_SOURCE_AUTO
    notes: List[str] = field(default_factory=list)
    demo: bool = False

    @property
    def last_month_label(self) -> str:
        for t in self.tenants:
            if t.data.last_month_label:
                return t.data.last_month_label
        return "Last month"

    @property
    def current_month_label(self) -> str:
        for t in self.tenants:
            if t.data.current_month_label:
                return t.data.current_month_label
        return "Current MTD"

    @property
    def has_cost_management_data(self) -> bool:
        return any(r.actual_last_month_cost is not None for r in self.all_records())

    @property
    def cost_basis_description(self) -> str:
        lm = self.last_month_label
        cm = self.current_month_label
        if self.cost_source == COST_SOURCE_RETAIL or not self.has_cost_management_data:
            suffix = " (including deallocated VMs)" if self.include_deallocated_cost else " (active/allocated VMs)"
            return f"Retail Prices API ({self.hours_per_month:g}h/month in {self.currency}){suffix}"
        if self.cost_source == COST_SOURCE_LAST_MONTH:
            return f"Azure Cost Management actual billed cost ({lm} in {self.currency})"
        if self.cost_source == COST_SOURCE_MTD:
            return f"Azure Cost Management {cm} month-to-date extrapolated to full month ({self.currency})"
        return (
            f"Azure Cost Management actual billed cost ({lm} baseline, {cm} MTD fallback for new VMs, "
            f"Retail {self.hours_per_month:g}h fallback if Cost Management unavailable)"
        )

    def all_records(self) -> List[LegacyVmRecord]:
        return [rec for tenant in self.tenants if tenant.fetched for rec in tenant.records]

    def totals_by_generation(self) -> Dict[str, GenerationSummary]:
        records = self.all_records()
        return _summarise_generations(records, self.generations)

    def grand_total(self) -> GenerationSummary:
        return _summarise_records("All legacy (v1-v3)", self.all_records())

    def all_sku_rows(self) -> List[SkuBreakdownRow]:
        return _summarise_skus(self.all_records())

    def all_subscription_rows(self) -> List[SubscriptionBreakdownRow]:
        return _summarise_subscriptions(self.all_records())

    def missing_tenants(self) -> List[str]:
        return [t.display_name for t in self.tenants if not t.fetched]

    @property
    def any_vmss(self) -> bool:
        return any(r.resource_type == TYPE_VMSS for r in self.all_records())

    def to_dict(self) -> Dict[str, Any]:
        by_gen = self.totals_by_generation()
        return {
            "tool": "azure-legacy-vm-report",
            "version": self.version,
            "generated_at": iso_utc(self.generated_at),
            "timezone": self.tz_name,
            "currency": self.currency,
            "hours_per_month": self.hours_per_month,
            "cost_source": self.cost_source,
            "cost_basis_description": self.cost_basis_description,
            "hike_policy": {
                "name": self.policy.name,
                "label": self.policy.label,
                "v1_hike_pct": self.policy.v1_hike_pct,
                "v2_hike_pct": self.policy.v2_hike_pct,
                "v3_hike_pct": self.policy.v3_hike_pct,
                "effective_date": "2027-02-01",
            },
            "generations_included": list(self.generations),
            "include_vmss": self.include_vmss,
            "include_deallocated_cost": self.include_deallocated_cost,
            "demo": self.demo,
            "totals": {
                "by_generation": {gen: by_gen[gen].to_dict() for gen in self.generations},
                "overall": self.grand_total().to_dict(),
                "missing_tenants": self.missing_tenants(),
            },
            "tenants": [tenant.to_dict() for tenant in self.tenants],
            "notes": list(self.notes),
        }


def _summarise_records(label: str, records: Iterable[LegacyVmRecord]) -> GenerationSummary:
    summary = GenerationSummary(generation=label)
    for rec in records:
        summary.resource_count += 1
        summary.instance_count += rec.instance_count
        if rec.power_state == POWER_DEALLOCATED:
            summary.deallocated_instances += rec.instance_count
        else:
            summary.running_instances += rec.instance_count
        summary.total_vcpus += rec.total_vcpus
        summary.current_monthly += rec.current_monthly
        summary.feb_monthly += rec.feb_monthly
        summary.monthly_delta += rec.monthly_delta
        summary.annual_delta += rec.annual_delta
        summary.provisioned_current_monthly += rec.provisioned_current_monthly
        summary.provisioned_feb_monthly += rec.provisioned_feb_monthly
        summary.provisioned_monthly_delta += rec.provisioned_monthly_delta
        summary.legacy_25_feb_monthly += round(rec.current_monthly * (1.0 + rec.legacy_25_hike_pct / 100.0), 2)
        summary.service_health_feb_monthly += round(
            rec.current_monthly * (1.0 + rec.service_health_hike_pct / 100.0), 2
        )
    summary.current_monthly = round(summary.current_monthly, 2)
    summary.feb_monthly = round(summary.feb_monthly, 2)
    summary.monthly_delta = round(summary.monthly_delta, 2)
    summary.annual_delta = round(summary.annual_delta, 2)
    summary.provisioned_current_monthly = round(summary.provisioned_current_monthly, 2)
    summary.provisioned_feb_monthly = round(summary.provisioned_feb_monthly, 2)
    summary.provisioned_monthly_delta = round(summary.provisioned_monthly_delta, 2)
    summary.legacy_25_feb_monthly = round(summary.legacy_25_feb_monthly, 2)
    summary.service_health_feb_monthly = round(summary.service_health_feb_monthly, 2)
    return summary


def _summarise_generations(
    records: Sequence[LegacyVmRecord], generations: Sequence[str]
) -> Dict[str, GenerationSummary]:
    grouped: Dict[str, List[LegacyVmRecord]] = {gen: [] for gen in generations}
    for rec in records:
        grouped.setdefault(rec.generation, []).append(rec)
    return {gen: _summarise_records(gen, grouped.get(gen, ())) for gen in generations}


def _summarise_skus(records: Sequence[LegacyVmRecord]) -> List[SkuBreakdownRow]:
    by_sku: Dict[str, SkuBreakdownRow] = {}
    regions_seen: Dict[str, set] = {}
    for rec in records:
        row = by_sku.get(rec.sku)
        if row is None:
            row = SkuBreakdownRow(
                sku=rec.sku,
                generation=rec.generation,
                series=rec.series,
                category=rec.category,
                vcpus_per_instance=rec.vcpus_per_instance,
                hike_pct=rec.hike_pct,
                retirement_date=rec.retirement_date,
                recommended_v5=rec.recommended_v5,
                recommended_current=rec.recommended_current,
            )
            by_sku[rec.sku] = row
            regions_seen[rec.sku] = set()
        row.resource_count += 1
        row.instance_count += rec.instance_count
        if rec.power_state == POWER_DEALLOCATED:
            row.deallocated_instances += rec.instance_count
        else:
            row.running_instances += rec.instance_count
        if rec.os_type.lower() == "windows":
            row.windows_instances += rec.instance_count
        else:
            row.linux_instances += rec.instance_count
        if rec.hybrid_benefit:
            row.ahb_instances += rec.instance_count
        if rec.region:
            regions_seen[rec.sku].add(rec.region)
        row.current_monthly = round(row.current_monthly + rec.current_monthly, 2)
        row.feb_monthly = round(row.feb_monthly + rec.feb_monthly, 2)
        row.monthly_delta = round(row.monthly_delta + rec.monthly_delta, 2)
        row.annual_delta = round(row.annual_delta + rec.annual_delta, 2)
        row.provisioned_current_monthly = round(row.provisioned_current_monthly + rec.provisioned_current_monthly, 2)
        row.provisioned_feb_monthly = round(row.provisioned_feb_monthly + rec.provisioned_feb_monthly, 2)

    for sku, row in by_sku.items():
        row.regions = sorted(regions_seen[sku])
        if row.current_monthly > 0:
            row.hike_pct = round((row.monthly_delta / row.current_monthly) * 100.0, 2)
        elif row.provisioned_current_monthly > 0:
            row.hike_pct = round(
                ((row.provisioned_feb_monthly - row.provisioned_current_monthly) / row.provisioned_current_monthly)
                * 100.0,
                2,
            )

    return sorted(
        by_sku.values(),
        key=lambda r: (-r.monthly_delta, -r.current_monthly, -r.provisioned_current_monthly, r.generation, r.sku),
    )


def _summarise_subscriptions(records: Sequence[LegacyVmRecord]) -> List[SubscriptionBreakdownRow]:
    by_sub: Dict[str, SubscriptionBreakdownRow] = {}
    for rec in records:
        key = rec.subscription_id.lower()
        row = by_sub.get(key)
        if row is None:
            row = SubscriptionBreakdownRow(
                subscription_id=rec.subscription_id,
                subscription_name=rec.subscription_name,
            )
            by_sub[key] = row
        if rec.generation == "v1":
            row.v1_instances += rec.instance_count
        elif rec.generation == "v2":
            row.v2_instances += rec.instance_count
        elif rec.generation == "v3":
            row.v3_instances += rec.instance_count
        row.total_instances += rec.instance_count
        row.total_vcpus += rec.total_vcpus
        row.current_monthly = round(row.current_monthly + rec.current_monthly, 2)
        row.feb_monthly = round(row.feb_monthly + rec.feb_monthly, 2)
        row.monthly_delta = round(row.monthly_delta + rec.monthly_delta, 2)
        row.annual_delta = round(row.annual_delta + rec.annual_delta, 2)
        row.provisioned_current_monthly = round(row.provisioned_current_monthly + rec.provisioned_current_monthly, 2)
        row.provisioned_feb_monthly = round(row.provisioned_feb_monthly + rec.provisioned_feb_monthly, 2)

    return sorted(
        by_sub.values(),
        key=lambda r: (-r.monthly_delta, -r.current_monthly, -r.provisioned_current_monthly, r.subscription_name.lower()),
    )


def build_report(
    tenant_data: Sequence[TenantData],
    *,
    version: str,
    generated_at: datetime,
    tz: tzinfo,
    tz_name: str,
    currency: str,
    hours_per_month: float,
    policy: HikePolicy,
    generations: Sequence[str] = LEGACY_GENERATIONS,
    include_vmss: bool = True,
    include_deallocated_cost: bool = False,
    cost_source: str = COST_SOURCE_AUTO,
    notes: Optional[Sequence[str]] = None,
    demo: bool = False,
) -> Report:
    gen_tuple = tuple(generations)
    tenant_reports: List[TenantReport] = []
    for data in tenant_data:
        by_gen = _summarise_generations(data.records, gen_tuple)
        total = _summarise_records("Total", data.records)
        skus = _summarise_skus(data.records)
        subs = _summarise_subscriptions(data.records)
        tenant_reports.append(
            TenantReport(
                data=data,
                by_generation=by_gen,
                total_summary=total,
                sku_rows=skus,
                subscription_rows=subs,
            )
        )
    return Report(
        version=version,
        generated_at=generated_at,
        tz=tz,
        tz_name=tz_name,
        currency=currency,
        hours_per_month=hours_per_month,
        policy=policy,
        generations=gen_tuple,
        include_vmss=include_vmss,
        include_deallocated_cost=include_deallocated_cost,
        cost_source=cost_source,
        tenants=tenant_reports,
        notes=list(notes or ()),
        demo=demo,
    )
