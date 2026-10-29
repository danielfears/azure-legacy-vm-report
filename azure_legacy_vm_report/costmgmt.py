"""Fetch actual per-VM billed costs and usage hours from Azure Cost Management plus DevTestLab schedules."""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .arm import ArmClient, ArmError
from .dates import UTC

log = logging.getLogger("azure_legacy_vm_report.costmgmt")

SCHEDULE_ARG_QUERY = "Resources | where type =~ 'microsoft.devtestlab/schedules' | project name, properties"
_CHUNK_SIZE = 150


@dataclass(frozen=True)
class BillingWindow:
    last_month_prefix: str        # e.g. "2026-09"
    last_month_label: str         # e.g. "Sep 2026"
    last_month_hours: float       # e.g. 720.0
    current_month_prefix: str     # e.g. "2026-10"
    current_month_label: str      # e.g. "Oct 2026"
    current_month_hours: float    # e.g. 744.0
    elapsed_current_hours: float  # e.g. 680.0
    query_from_iso: str           # e.g. "2026-09-01T00:00:00Z"
    query_to_iso: str             # e.g. "2026-10-29T23:59:59Z"


@dataclass(frozen=True)
class VmScheduleInfo:
    status: str       # "Enabled" or "Disabled"
    daily_time: str   # e.g. "19:00"
    timezone: str     # e.g. "GMT Standard Time"


@dataclass
class ActualVmUsage:
    last_month_cost: float = 0.0
    last_month_hours: float = 0.0
    mtd_cost: float = 0.0
    mtd_hours: float = 0.0
    mtd_extrapolated_cost: float = 0.0
    mtd_extrapolated_hours: float = 0.0
    currency: str = ""
    has_data: bool = False


def compute_billing_window(as_of: datetime) -> BillingWindow:
    """Compute the previous complete calendar month and current month-to-date window around ``as_of``."""
    utc_now = as_of.astimezone(UTC) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    cur_year, cur_month = utc_now.year, utc_now.month
    if cur_month == 1:
        prev_year, prev_month = cur_year - 1, 12
    else:
        prev_year, prev_month = cur_year, cur_month - 1

    prev_days = calendar.monthrange(prev_year, prev_month)[1]
    cur_days = calendar.monthrange(cur_year, cur_month)[1]

    last_prefix = f"{prev_year:04d}-{prev_month:02d}"
    cur_prefix = f"{cur_year:04d}-{cur_month:02d}"
    last_label = datetime(prev_year, prev_month, 1, tzinfo=UTC).strftime("%b %Y")
    cur_label = datetime(cur_year, cur_month, 1, tzinfo=UTC).strftime("%b %Y")

    cur_start = datetime(cur_year, cur_month, 1, 0, 0, 0, tzinfo=UTC)
    elapsed_hours = max(24.0, (utc_now - cur_start).total_seconds() / 3600.0)
    cur_total_hours = float(cur_days * 24)
    elapsed_hours = min(elapsed_hours, cur_total_hours)

    query_from = f"{last_prefix}-01T00:00:00Z"
    query_to = utc_now.strftime("%Y-%m-%dT23:59:59Z")

    return BillingWindow(
        last_month_prefix=last_prefix,
        last_month_label=last_label,
        last_month_hours=float(prev_days * 24),
        current_month_prefix=cur_prefix,
        current_month_label=cur_label,
        current_month_hours=cur_total_hours,
        elapsed_current_hours=elapsed_hours,
        query_from_iso=query_from,
        query_to_iso=query_to,
    )


def format_daily_time(raw_time: Any) -> str:
    """Turn DevTestLab's '1900' or '0200' string into '19:00' or '02:00'."""
    text = str(raw_time or "").strip()
    if len(text) == 4 and text.isdigit():
        return f"{text[:2]}:{text[2:]}"
    if len(text) == 3 and text.isdigit():
        return f"0{text[0]}:{text[1:]}"
    return text


def fetch_vm_schedules(
    client: ArmClient,
    subscriptions: Optional[Sequence[str]] = None,
    *,
    api_version: str = "2022-10-01",
) -> Dict[str, VmScheduleInfo]:
    """Return a map of lower-case VM ``resource_id`` -> ``VmScheduleInfo`` from Azure Resource Graph."""
    schedules: Dict[str, VmScheduleInfo] = {}
    try:
        rows = client.query_resource_graph(
            SCHEDULE_ARG_QUERY,
            subscriptions=subscriptions if subscriptions else None,
            api_version=api_version,
        )
    except ArmError as exc:
        log.debug("Could not query microsoft.devtestlab/schedules: %s", exc)
        return schedules

    for row in rows:
        props = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        target = str(props.get("targetResourceId") or "").strip().lower()
        if not target:
            continue
        status = str(props.get("status") or "").strip()
        daily = props.get("dailyRecurrence") if isinstance(props.get("dailyRecurrence"), dict) else {}
        time_str = format_daily_time(daily.get("time"))
        tz_str = str(props.get("timeZoneId") or "").strip()
        # Prefer Enabled schedules if multiple schedule resources target the same VM
        existing = schedules.get(target)
        if existing is None or status.lower() == "enabled":
            schedules[target] = VmScheduleInfo(status=status, daily_time=time_str, timezone=tz_str)
    return schedules


def fetch_subscription_actual_costs(
    client: ArmClient,
    subscription_id: str,
    resource_ids: Sequence[str],
    window: BillingWindow,
    *,
    api_version: str = "2023-11-01",
) -> Tuple[Dict[str, ActualVmUsage], Optional[str]]:
    """Query Azure Cost Management for ``resource_ids`` in ``subscription_id`` over ``window``.

    Returns ``(usage_by_lower_resource_id, warning_if_failed)``.
    """
    usage_map: Dict[str, ActualVmUsage] = {rid.lower(): ActualVmUsage(has_data=True) for rid in resource_ids}
    if not resource_ids:
        return usage_map, None

    path = f"/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/query"
    unique_ids = list(dict.fromkeys(rid for rid in resource_ids if rid))

    for start in range(0, len(unique_ids), _CHUNK_SIZE):
        chunk = unique_ids[start: start + _CHUNK_SIZE]
        payload: Dict[str, Any] = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {
                "from": window.query_from_iso,
                "to": window.query_to_iso,
            },
            "dataset": {
                "granularity": "None",
                "aggregation": {
                    "totalCost": {"name": "Cost", "function": "Sum"},
                    "usageQuantity": {"name": "UsageQuantity", "function": "Sum"},
                },
                "grouping": [
                    {"type": "Dimension", "name": "ResourceId"},
                    {"type": "Dimension", "name": "BillingMonth"},
                    {"type": "Dimension", "name": "MeterCategory"},
                ],
                "filter": {
                    "and": [
                        {
                            "dimensions": {
                                "name": "MeterCategory",
                                "operator": "In",
                                "values": ["Virtual Machines", "Virtual Machines Licenses"],
                            }
                        },
                        {
                            "dimensions": {
                                "name": "ResourceId",
                                "operator": "In",
                                "values": chunk,
                            }
                        },
                    ]
                },
            },
        }
        try:
            reply = client.post_json(path, api_version, payload)
        except ArmError as exc:
            return {}, f"Could not read Cost Management for subscription {subscription_id}: {exc}"

        _accumulate_cost_rows(reply, usage_map, window)

    _finalise_extrapolation(usage_map, window)
    return usage_map, None


def _accumulate_cost_rows(
    reply: Mapping[str, Any],
    usage_map: Dict[str, ActualVmUsage],
    window: BillingWindow,
) -> None:
    props = reply.get("properties") if isinstance(reply.get("properties"), dict) else {}
    columns = props.get("columns") if isinstance(props.get("columns"), list) else []
    rows = props.get("rows") if isinstance(props.get("rows"), list) else []

    col_idx = {
        str(col.get("name") or "").lower(): idx
        for idx, col in enumerate(columns)
        if isinstance(col, dict)
    }
    i_cost = col_idx.get("cost", col_idx.get("pretaxcost", 0))
    i_qty = col_idx.get("usagequantity", 1)
    i_rid = col_idx.get("resourceid", 2)
    i_month = col_idx.get("billingmonth", 3)
    i_cat = col_idx.get("metercategory", 4)
    i_cur = col_idx.get("currency", 5)

    for row in rows:
        if not isinstance(row, list) or len(row) <= max(i_cost, i_qty, i_rid, i_month, i_cat):
            continue
        rid = str(row[i_rid] or "").strip().lower()
        entry = usage_map.get(rid)
        if entry is None:
            entry = ActualVmUsage(has_data=True)
            usage_map[rid] = entry
        try:
            cost = float(row[i_cost] or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        try:
            qty = float(row[i_qty] or 0.0)
        except (TypeError, ValueError):
            qty = 0.0
        bmonth = str(row[i_month] or "").strip()
        mcat = str(row[i_cat] or "").strip().lower()
        if i_cur < len(row) and row[i_cur]:
            entry.currency = str(row[i_cur]).strip().upper()

        is_compute_meter = mcat == "virtual machines"
        if bmonth.startswith(window.last_month_prefix):
            entry.last_month_cost = round(entry.last_month_cost + cost, 4)
            if is_compute_meter:
                entry.last_month_hours = round(entry.last_month_hours + qty, 2)
        elif bmonth.startswith(window.current_month_prefix):
            entry.mtd_cost = round(entry.mtd_cost + cost, 4)
            if is_compute_meter:
                entry.mtd_hours = round(entry.mtd_hours + qty, 2)


def _finalise_extrapolation(usage_map: Dict[str, ActualVmUsage], window: BillingWindow) -> None:
    # Cost Management has an ~8-24h ingestion lag, so observe the max single-VM MTD hours when possible
    # so a 24/7 VM in the current month extrapolates accurately to a full month.
    observed_single_vm_hours = [
        u.mtd_hours for u in usage_map.values() if 24.0 <= u.mtd_hours <= window.current_month_hours
    ]
    effective_elapsed = (
        max(observed_single_vm_hours)
        if observed_single_vm_hours
        else window.elapsed_current_hours
    )
    effective_elapsed = max(24.0, min(effective_elapsed, window.current_month_hours))
    scale = window.current_month_hours / effective_elapsed if effective_elapsed > 0 else 1.0

    for entry in usage_map.values():
        entry.last_month_cost = round(entry.last_month_cost, 2)
        entry.mtd_cost = round(entry.mtd_cost, 2)
        entry.mtd_extrapolated_cost = round(entry.mtd_cost * scale, 2)
        entry.mtd_extrapolated_hours = round(entry.mtd_hours * scale, 1)
