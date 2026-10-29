"""Fetch actual per-VM billed costs and usage hours from Azure Cost Management plus DevTestLab schedules."""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .arm import ArmClient, ArmError
from .dates import UTC

log = logging.getLogger("azure_legacy_vm_report.costmgmt")

SCHEDULE_ARG_QUERY = """\
Resources
| where type in~ (
    'microsoft.devtestlab/schedules',
    'microsoft.insights/autoscalesettings',
    'microsoft.containerservice/managedclusters',
    'microsoft.desktopvirtualization/scalingplans'
)
| project id, name, type=tolower(type), subscriptionId=tolower(subscriptionId),
    resourceGroup=tolower(resourceGroup), location=tolower(location), properties
"""
_CHUNK_SIZE = 500

_SCHEDULE_TAG_KEYS = re.compile(
    r"^(?:autoshutdown|autostartup|auto[-_]?shutdown|auto[-_]?start|schedule|startstopschedule|"
    r"shutdownschedule|startupschedule|stoptime|starttime|uptime|powerschedule|workinghours|"
    r"businesshours|maintenancewindow)$",
    re.IGNORECASE,
)


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
    status: str = ""            # "Enabled" or "Disabled"
    daily_time: str = ""        # e.g. "19:00"
    timezone: str = ""          # e.g. "GMT Standard Time"
    autoscale_summary: str = "" # e.g. "Autoscale (1..5)" or "AKS Autoscale (1..3)"
    aks_cluster: str = ""       # e.g. "aks-uks-cort-shrd-core-01"
    aks_pool: str = ""          # e.g. "admagentpool"


@dataclass
class AksPoolProfile:
    cluster_id: str
    cluster_name: str
    subscription_id: str
    resource_group: str
    node_resource_group: str
    location: str
    pool_name: str
    vm_size: str
    count: int
    min_count: Optional[int]
    max_count: Optional[int]
    enable_auto_scaling: bool
    os_type: str
    power_state: str
    matched_to_vmss: bool = False


@dataclass
class ScheduleCatalog:
    by_resource_id: Dict[str, VmScheduleInfo] = field(default_factory=dict)
    aks_pools_by_key: Dict[Tuple[str, str, str], AksPoolProfile] = field(default_factory=dict)
    aks_pools: List[AksPoolProfile] = field(default_factory=list)


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


def fetch_schedule_catalog(
    client: ArmClient,
    subscriptions: Optional[Sequence[str]] = None,
    *,
    api_version: str = "2022-10-01",
) -> ScheduleCatalog:
    """Fetch portal auto-shutdown schedules, Azure Monitor autoscale settings, and AKS node pools."""
    catalog = ScheduleCatalog()
    try:
        rows = client.query_resource_graph(
            SCHEDULE_ARG_QUERY,
            subscriptions=subscriptions if subscriptions else None,
            api_version=api_version,
        )
    except ArmError as exc:
        log.debug("Could not query schedule/context resources: %s", exc)
        return catalog

    for row in rows:
        rtype = str(row.get("type") or "").strip().lower()
        props = row.get("properties") if isinstance(row.get("properties"), dict) else {}

        if rtype == "microsoft.devtestlab/schedules" or not rtype:
            target = str(props.get("targetResourceId") or "").strip().lower()
            if not target:
                continue
            status = str(props.get("status") or "").strip()
            daily = props.get("dailyRecurrence") if isinstance(props.get("dailyRecurrence"), dict) else {}
            time_str = format_daily_time(daily.get("time"))
            tz_str = str(props.get("timeZoneId") or "").strip()
            existing = catalog.by_resource_id.get(target)
            if existing is None or status.lower() == "enabled":
                catalog.by_resource_id[target] = VmScheduleInfo(
                    status=status,
                    daily_time=time_str,
                    timezone=tz_str,
                    autoscale_summary=existing.autoscale_summary if existing else "",
                )

        elif rtype == "microsoft.insights/autoscalesettings":
            target = str(props.get("targetResourceUri") or "").strip().lower()
            if not target:
                continue
            enabled = bool(props.get("enabled"))
            profiles = props.get("profiles") if isinstance(props.get("profiles"), list) else []
            cap_str = ""
            if profiles and isinstance(profiles[0], dict):
                cap = profiles[0].get("capacity") if isinstance(profiles[0].get("capacity"), dict) else {}
                mn, mx = cap.get("minimum"), cap.get("maximum")
                if mn is not None and mx is not None:
                    cap_str = f" ({mn}..{mx})"
            summary = f"Autoscale{' On' if enabled else ' Off'}{cap_str}"
            existing = catalog.by_resource_id.get(target)
            catalog.by_resource_id[target] = VmScheduleInfo(
                status=existing.status if existing else "",
                daily_time=existing.daily_time if existing else "",
                timezone=existing.timezone if existing else "",
                autoscale_summary=summary,
            )

        elif rtype == "microsoft.containerservice/managedclusters":
            sub_id = str(row.get("subscriptionId") or "").strip().lower()
            rg = str(row.get("resourceGroup") or "").strip()
            loc = str(row.get("location") or "uksouth").strip().lower()
            cname = str(row.get("name") or "").strip()
            cid = str(row.get("id") or "").strip()
            node_rg = str(props.get("nodeResourceGroup") or "").strip().lower()
            pools = props.get("agentPoolProfiles") if isinstance(props.get("agentPoolProfiles"), list) else []
            for p in pools:
                if not isinstance(p, dict):
                    continue
                pname = str(p.get("name") or "").strip()
                vmsize = str(p.get("vmSize") or "").strip()
                if not pname or not vmsize:
                    continue
                cnt = int(p.get("count") or 0) if str(p.get("count") or "").isdigit() else 0
                min_c = int(p["minCount"]) if str(p.get("minCount") or "").isdigit() else None
                max_c = int(p["maxCount"]) if str(p.get("maxCount") or "").isdigit() else None
                autoscale = bool(p.get("enableAutoScaling"))
                os_t = str(p.get("osType") or "Linux")
                pstate_obj = p.get("powerState") if isinstance(p.get("powerState"), dict) else {}
                pstate = str(pstate_obj.get("code") or "Running")
                prof = AksPoolProfile(
                    cluster_id=cid,
                    cluster_name=cname,
                    subscription_id=sub_id,
                    resource_group=rg,
                    node_resource_group=node_rg,
                    location=loc,
                    pool_name=pname,
                    vm_size=vmsize,
                    count=cnt,
                    min_count=min_c,
                    max_count=max_c,
                    enable_auto_scaling=autoscale,
                    os_type=os_t,
                    power_state=pstate,
                )
                catalog.aks_pools.append(prof)
                if sub_id and node_rg and pname:
                    catalog.aks_pools_by_key[(sub_id, node_rg, pname.lower())] = prof

    return catalog


def fetch_vm_schedules(
    client: ArmClient,
    subscriptions: Optional[Sequence[str]] = None,
    *,
    api_version: str = "2022-10-01",
) -> Dict[str, VmScheduleInfo]:
    """Backwards-compatible wrapper returning the per-resource ``VmScheduleInfo`` map."""
    return fetch_schedule_catalog(client, subscriptions, api_version=api_version).by_resource_id


def infer_workload_and_schedule(
    *,
    resource_type_raw: str,
    name: str,
    resource_group: str,
    subscription_id: str,
    tags: Optional[Mapping[str, Any]],
    schedule_info: Optional[VmScheduleInfo],
    aks_pools_by_key: Optional[Mapping[Tuple[str, str, str], AksPoolProfile]] = None,
    default_hours: float = 730.0,
) -> Tuple[str, str, float]:
    """Infer ``(deployment_kind, schedule_summary, inferred_hours_per_month)`` for any VM/pool."""
    rtype = (resource_type_raw or "").strip().lower()
    rg_lower = (resource_group or "").strip().lower()
    name_lower = (name or "").strip().lower()
    sub_lower = (subscription_id or "").strip().lower()
    tag_map: Dict[str, str] = {}
    if isinstance(tags, Mapping):
        for k, v in tags.items():
            if k is not None and v is not None:
                tag_map[str(k).strip()] = str(v).strip()
    tag_lower = {k.lower(): v for k, v in tag_map.items()}

    # 1. Determine deployment kind
    aks_pool_name = (
        tag_lower.get("aks-managed-poolname")
        or tag_lower.get("poolname")
        or ""
    )
    aks_prof: Optional[AksPoolProfile] = None
    if aks_pool_name and aks_pools_by_key and sub_lower and rg_lower:
        aks_prof = aks_pools_by_key.get((sub_lower, rg_lower, aks_pool_name.lower()))

    if rtype == "microsoft.batch/batchaccounts/pools":
        deployment_kind = "Batch Pool"
    elif rtype == "microsoft.machinelearningservices/workspaces/computes":
        deployment_kind = "ML Compute"
    elif rtype == "microsoft.containerservice/managedclusters":
        deployment_kind = f"AKS Node Pool ({name})"
    elif aks_prof is not None:
        aks_prof.matched_to_vmss = True
        deployment_kind = f"AKS Node Pool ({aks_prof.cluster_name}/{aks_prof.pool_name})"
    elif aks_pool_name or "compute.aks.billing" in tag_lower or rg_lower.startswith("mc_"):
        pool_suffix = f" ({aks_pool_name})" if aks_pool_name else ""
        deployment_kind = f"AKS Node Pool{pool_suffix}"
    elif "databricks" in tag_lower or "databricksenvironment" in tag_lower or "databricks" in rg_lower:
        deployment_kind = "Databricks Node"
    elif name_lower.startswith(("ocp", "aro-")) or "openshift" in rg_lower:
        deployment_kind = "OpenShift / ARO Node"
    elif any(k.startswith(("wvd", "avd", "ms_rdp")) for k in tag_lower) or "avd" in rg_lower or "wvd" in rg_lower:
        deployment_kind = "AVD Session Host"
    elif "devtestlab" in tag_lower or "labvm" in tag_lower or rtype.startswith("microsoft.devtestlab/"):
        deployment_kind = "DevTest Lab VM"
    elif "job_started" in tag_lower or "packer" in tag_lower or "image-builder" in name_lower:
        deployment_kind = "Ephemeral / CI Job VM"
    elif rtype == "microsoft.compute/virtualmachinescalesets":
        deployment_kind = "VM Scale Set"
    else:
        deployment_kind = "Standalone VM"

    # 2. Collect all schedule, runbook tag, and autoscaler signals
    sched_parts: List[str] = []
    inferred_hours = default_hours

    if schedule_info and schedule_info.status:
        if schedule_info.daily_time:
            sched_parts.append(f"{schedule_info.status} ({schedule_info.daily_time})")
        else:
            sched_parts.append(schedule_info.status)
        if schedule_info.status.lower() == "enabled":
            inferred_hours = min(inferred_hours, 365.0)

    # Check runbook / schedule tags
    auto_off_tag = tag_lower.get("autoshutdown") or tag_lower.get("auto-shutdown") or tag_lower.get("auto_shutdown")
    auto_on_tag = tag_lower.get("autostartup") or tag_lower.get("auto-startup") or tag_lower.get("auto_startup")
    if auto_off_tag and auto_on_tag:
        sched_parts.append("Runbook: Autostartup+Autoshutdown")
        if auto_off_tag.lower() not in ("false", "0", "no", "disabled"):
            inferred_hours = min(inferred_hours, 260.0)
    else:
        for k, v in tag_map.items():
            if _SCHEDULE_TAG_KEYS.match(k) and v:
                sched_parts.append(f"Tag {k}={v[:24]}")
                if v.lower() not in ("false", "0", "no", "disabled", "none", "24x7", "24/7"):
                    inferred_hours = min(inferred_hours, 365.0)
                break

    if aks_prof is not None and aks_prof.enable_auto_scaling:
        mn = aks_prof.min_count if aks_prof.min_count is not None else 0
        mx = aks_prof.max_count if aks_prof.max_count is not None else aks_prof.count
        sched_parts.append(f"AKS Autoscale ({mn}..{mx})")
    elif schedule_info and schedule_info.autoscale_summary:
        sched_parts.append(schedule_info.autoscale_summary)

    if deployment_kind == "Ephemeral / CI Job VM":
        inferred_hours = min(inferred_hours, 20.0)

    return deployment_kind, " · ".join(sched_parts), inferred_hours


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
            reply = client.post_json(
                path,
                api_version,
                payload,
                extra_headers={"ClientType": "AzurePortal"},
            )
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
