"""CSV and JSON output for legacy VM inventory, SKU breakdown, subscription breakdown and generation summary."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, Iterable, List, Sequence

from .model import LegacyVmRecord
from .report import GenerationSummary, Report, SkuBreakdownRow, SubscriptionBreakdownRow
from .textfmt import clean_text, escape_invisible

_FORMULA_START = ("=", "+", "-", "@")

VM_FIELDS = [
    "tenant_id",
    "tenant_name",
    "subscription_id",
    "subscription_name",
    "resource_group",
    "name",
    "resource_type",
    "deployment_kind",
    "region",
    "sku",
    "generation",
    "series",
    "category",
    "instance_count",
    "vcpus_per_instance",
    "total_vcpus",
    "os_type",
    "license_type",
    "hybrid_benefit",
    "priority",
    "power_state",
    "is_billed_now",
    "auto_shutdown_schedule",
    "cost_basis_used",
    "currency",
    "hourly_rate",
    "feb_hourly_rate",
    "hours_per_month",
    "inferred_hours_per_month",
    "actual_last_month_cost",
    "actual_last_month_hours",
    "actual_mtd_cost",
    "actual_mtd_extrapolated_cost",
    "actual_mtd_hours",
    "retail_active_monthly",
    "schedule_adjusted_monthly",
    "current_monthly",
    "feb_monthly",
    "monthly_delta",
    "annual_delta",
    "hike_pct",
    "hike_reason",
    "provisioned_current_monthly",
    "provisioned_feb_monthly",
    "provisioned_monthly_delta",
    "pricing_model",
    "price_source",
    "lifecycle_stage",
    "retirement_date",
    "recommended_v5",
    "recommended_current",
    "disk_controller_note",
    "resource_id",
]

SKU_FIELDS = [
    "tenant_id",
    "tenant_name",
    "sku",
    "generation",
    "series",
    "category",
    "vcpus_per_instance",
    "resource_count",
    "instance_count",
    "running_instances",
    "deallocated_instances",
    "linux_instances",
    "windows_instances",
    "ahb_instances",
    "regions",
    "currency",
    "current_monthly",
    "feb_monthly",
    "monthly_delta",
    "annual_delta",
    "hike_pct",
    "provisioned_current_monthly",
    "provisioned_feb_monthly",
    "retirement_date",
    "recommended_v5",
    "recommended_current",
]

SUBSCRIPTION_FIELDS = [
    "tenant_id",
    "tenant_name",
    "subscription_id",
    "subscription_name",
    "v1_instances",
    "v2_instances",
    "v3_instances",
    "total_instances",
    "total_vcpus",
    "currency",
    "current_monthly",
    "feb_monthly",
    "monthly_delta",
    "annual_delta",
    "provisioned_current_monthly",
    "provisioned_feb_monthly",
]

SUMMARY_FIELDS = [
    "tenant_id",
    "tenant_name",
    "retrieved",
    "generation",
    "resource_count",
    "instance_count",
    "running_instances",
    "deallocated_instances",
    "total_vcpus",
    "currency",
    "current_monthly",
    "feb_monthly",
    "monthly_delta",
    "annual_delta",
    "effective_hike_pct",
    "provisioned_current_monthly",
    "provisioned_feb_monthly",
    "provisioned_monthly_delta",
    "legacy_25_feb_monthly",
    "service_health_feb_monthly",
]


def safe_cell(value: Any) -> Any:
    """Make a cell safe for spreadsheets and terminals; numbers pass through."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value
    text = clean_text(value)
    if text and text[0] in _FORMULA_START:
        return "'" + text
    return text


def _write(fields: Sequence[str], rows: Iterable[Dict[str, Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), lineterminator="\r\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: safe_cell(row.get(key)) for key in fields})
    return buffer.getvalue()


def _vm_row(rec: LegacyVmRecord) -> Dict[str, Any]:
    return rec.to_dict()


def render_vms_csv(report: Report) -> str:
    return _write(VM_FIELDS, (_vm_row(rec) for rec in report.all_records()))


def render_skus_csv(report: Report) -> str:
    rows: List[Dict[str, Any]] = []
    for tenant in report.tenants:
        if not tenant.fetched:
            continue
        for sku_row in tenant.sku_rows:
            rows.append(_sku_dict(tenant.tenant_id, tenant.display_name, report.currency, sku_row))
    if len(report.tenants) > 1:
        for sku_row in report.all_sku_rows():
            rows.append(_sku_dict("*", "All tenants", report.currency, sku_row))
    return _write(SKU_FIELDS, rows)


def _sku_dict(tenant_id: str, tenant_name: str, currency: str, row: SkuBreakdownRow) -> Dict[str, Any]:
    data = row.to_dict()
    data["tenant_id"] = tenant_id
    data["tenant_name"] = tenant_name
    data["currency"] = currency
    data["regions"] = "; ".join(row.regions)
    return data


def render_subscriptions_csv(report: Report) -> str:
    rows: List[Dict[str, Any]] = []
    for tenant in report.tenants:
        if not tenant.fetched:
            continue
        for sub_row in tenant.subscription_rows:
            rows.append(_sub_dict(tenant.tenant_id, tenant.display_name, report.currency, sub_row))
    return _write(SUBSCRIPTION_FIELDS, rows)


def _sub_dict(tenant_id: str, tenant_name: str, currency: str, row: SubscriptionBreakdownRow) -> Dict[str, Any]:
    data = row.to_dict()
    data["tenant_id"] = tenant_id
    data["tenant_name"] = tenant_name
    data["currency"] = currency
    return data


def render_summary_csv(report: Report) -> str:
    rows: List[Dict[str, Any]] = []

    def make_row(
        tenant_id: str,
        tenant_name: str,
        retrieved: bool,
        has_figures: bool,
        summary: GenerationSummary,
    ) -> Dict[str, Any]:
        figures = summary.to_dict()
        generation = figures.pop("generation")
        if not has_figures:
            figures = dict.fromkeys(figures)
        return {
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
            "retrieved": retrieved,
            "generation": generation,
            "currency": report.currency if has_figures else None,
            **figures,
        }

    for tenant in report.tenants:
        ok = tenant.fetched
        for gen in report.generations:
            rows.append(make_row(tenant.tenant_id, tenant.display_name, ok, ok, tenant.by_generation[gen]))
        rows.append(make_row(tenant.tenant_id, tenant.display_name, ok, ok, tenant.total_summary))

    if len(report.tenants) > 1:
        any_ok = any(t.fetched for t in report.tenants)
        all_ok = all(t.fetched for t in report.tenants)
        by_gen = report.totals_by_generation()
        for gen in report.generations:
            rows.append(make_row("*", "All tenants", all_ok, any_ok, by_gen[gen]))
        rows.append(make_row("*", "All tenants", all_ok, any_ok, report.grand_total()))
    return _write(SUMMARY_FIELDS, rows)


def render_json(report: Report) -> str:
    return escape_invisible(json.dumps(report.to_dict(), indent=2, ensure_ascii=False)) + "\n"
