"""Discover VMs and VM Scale Sets across a tenant and filter/price legacy v1, v2 and v3 SKUs."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from .arm import KIND_PERMISSION, ArmClient, ArmError
from .auth import AuthError, TokenProvider, is_guid
from .config import TenantSpec
from .costmgmt import (
    ActualVmUsage,
    ScheduleCatalog,
    compute_billing_window,
    fetch_schedule_catalog,
    fetch_subscription_actual_costs,
    infer_workload_and_schedule,
)
from .dates import UTC
from .model import (
    COST_SOURCE_AUTO,
    COST_SOURCE_RETAIL,
    TYPE_VM,
    TYPE_VMSS,
    LegacyVmRecord,
    NameMaps,
    build_legacy_record,
    normalise_os_type,
    normalise_power_state,
    normalise_priority,
)
from .pricing import DEFAULT_HOURS_PER_MONTH, HikePolicy, PricingClient
from .skus import LEGACY_GENERATIONS, SkuInfo, classify_vm_sku
from .transport import Transport

log = logging.getLogger("azure_legacy_vm_report.collect")

LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"
LEVEL_INFO = "info"

FETCH_OK = "ok"
FETCH_FAILED = "failed"

ARG_VM_QUERY = """\
Resources
| where type in~ (
    'microsoft.compute/virtualmachines',
    'microsoft.compute/virtualmachinescalesets',
    'microsoft.batch/batchaccounts/pools',
    'microsoft.machinelearningservices/workspaces/computes'
)
| project id, name, type, subscriptionId, resourceGroup, location, tags,
    vmssId = tolower(tostring(properties.virtualMachineScaleSet.id)),
    vmSize = coalesce(
        tostring(properties.hardwareProfile.vmSize),
        tostring(properties.vmSize),
        tostring(properties.properties.vmSize)
    ),
    skuName = tostring(sku.name),
    skuCapacity = coalesce(
        toint(sku.capacity),
        toint(properties.scaleSettings.fixedScale.targetDedicatedNodes) + toint(properties.scaleSettings.fixedScale.targetLowPriorityNodes),
        toint(properties.properties.scaleSettings.minNodeCount)
    ),
    osType = coalesce(
        tostring(properties.storageProfile.osDisk.osType),
        tostring(properties.virtualMachineProfile.storageProfile.osDisk.osType)
    ),
    licenseType = coalesce(
        tostring(properties.licenseType),
        tostring(properties.virtualMachineProfile.licenseType)
    ),
    priority = coalesce(
        tostring(properties.priority),
        tostring(properties.virtualMachineProfile.priority)
    ),
    powerState = coalesce(
        tostring(properties.extended.instanceView.powerState.code),
        tostring(properties.allocationState),
        tostring(properties.properties.allocationState)
    )
"""


@dataclass
class Issue:
    level: str
    feature: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {"level": self.level, "feature": self.feature, "message": self.message}


@dataclass
class CollectOptions:
    generations: Tuple[str, ...] = LEGACY_GENERATIONS
    subscription_filter: Tuple[str, ...] = ()
    include_vmss: bool = True
    include_deallocated_cost: bool = False
    hours_per_month: float = DEFAULT_HOURS_PER_MONTH
    cost_source: str = COST_SOURCE_AUTO
    as_of: Optional[datetime] = None
    use_resource_graph: bool = True
    resource_graph_api: str = "2022-10-01"
    compute_api: str = "2024-07-01"
    cost_management_api: str = "2023-11-01"
    subscriptions_api: str = "2022-12-01"
    tenants_api: str = "2022-12-01"
    timeout: float = 60.0
    max_retries: int = 4


@dataclass
class TenantData:
    spec: TenantSpec
    display_name: str = ""
    default_domain: str = ""
    subscription_count: Optional[int] = None
    total_resources_scanned: int = 0
    total_instances_scanned: int = 0
    modern_resources_skipped: int = 0
    cost_management_subs_queried: int = 0
    cost_management_subs_succeeded: int = 0
    last_month_label: str = ""
    current_month_label: str = ""
    records: List[LegacyVmRecord] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    fetch_status: str = FETCH_FAILED
    discovery_method: str = ""
    fatal: bool = False

    @property
    def has_errors(self) -> bool:
        return self.fatal or any(issue.level == LEVEL_ERROR for issue in self.issues)


def collect_tenant(
    spec: TenantSpec,
    *,
    tokens: TokenProvider,
    transport: Transport,
    endpoint: str,
    pricing: PricingClient,
    policy: HikePolicy,
    options: CollectOptions,
    sleep: Optional[Callable[[float], None]] = None,
) -> TenantData:
    """Gather all v1, v2 and v3 VM and VMSS deployments visible in one tenant."""
    data = TenantData(spec=spec, display_name=spec.name or spec.tenant_id)
    token_key = spec.tenant_id
    try:
        token = tokens.get_token(token_key)
    except AuthError as exc:
        data.issues.append(Issue(LEVEL_ERROR, "authentication", str(exc)))
        data.fatal = True
        return data

    if not is_guid(spec.tenant_id):
        if is_guid(token.tenant_id):
            spec = data.spec = replace(spec, tenant_id=token.tenant_id.lower())
        else:
            data.issues.append(Issue(
                LEVEL_WARNING, "tenant",
                f"Could not resolve tenant GUID for {token_key}; use the tenant GUID with --tenant."
            ))

    extra: Dict[str, Any] = {"sleep": sleep} if sleep else {}
    client = ArmClient(
        token_key, tokens, endpoint, transport,
        timeout=options.timeout, max_retries=options.max_retries, **extra,
    )
    names = _collect_names(client, data, options)
    target_subs = _resolve_target_subscriptions(data, names, options.subscription_filter)

    raw_rows: Optional[List[Dict[str, Any]]] = None
    if options.use_resource_graph:
        raw_rows = _try_resource_graph(client, data, target_subs, options)

    if raw_rows is None:
        raw_rows = _collect_via_compute_arm(client, data, names, target_subs, options)

    if raw_rows is None:
        data.fatal = True
        return data

    data.fetch_status = FETCH_OK
    allowed_gens: Set[str] = {g.lower() for g in options.generations}
    allowed_subs: Optional[Set[str]] = {s.lower() for s in target_subs} if target_subs else None

    window = compute_billing_window(options.as_of or datetime.now(UTC))
    data.last_month_label = window.last_month_label
    data.current_month_label = window.current_month_label

    candidates: List[Tuple[Dict[str, Any], SkuInfo, bool, str, int]] = []
    subs_with_legacy: Dict[str, List[str]] = {}

    # Identify Flexible VM Scale Sets that already have child Microsoft.Compute/virtualMachines
    # in the result set so we never double-count the parent scale set and its child VMs.
    vmss_with_child_vms: Set[str] = {
        str(r.get("vmssId") or "").strip().lower()
        for r in raw_rows
        if str(r.get("type") or "").strip().lower() == "microsoft.compute/virtualmachines"
        and str(r.get("vmssId") or "").strip()
    }

    for row in raw_rows:
        rtype = str(row.get("type") or "").strip().lower()
        rid = str(row.get("id") or "")
        if rtype == "microsoft.compute/virtualmachinescalesets" and rid.lower() in vmss_with_child_vms:
            continue
        is_scale_resource = rtype in (
            "microsoft.compute/virtualmachinescalesets",
            "microsoft.batch/batchaccounts/pools",
            "microsoft.machinelearningservices/workspaces/computes",
        )
        if rtype == "microsoft.compute/virtualmachinescalesets" and not options.include_vmss:
            continue
        sub_id = str(row.get("subscriptionId") or "").strip().lower()
        if allowed_subs is not None and sub_id not in allowed_subs:
            continue

        raw_sku = str(row.get("skuName") or row.get("vmSize") or "").strip()
        if not raw_sku:
            continue
        capacity = _safe_int(row.get("skuCapacity"), default=1) if is_scale_resource else 1
        data.total_resources_scanned += 1
        data.total_instances_scanned += max(0, capacity)

        sku_info = classify_vm_sku(raw_sku)
        if sku_info is None:
            data.modern_resources_skipped += 1
            continue
        if sku_info.generation.lower() not in allowed_gens:
            continue

        candidates.append((row, sku_info, is_scale_resource, sub_id, capacity))
        if rid and sub_id:
            subs_with_legacy.setdefault(sub_id, []).append(rid)

    catalog = ScheduleCatalog()
    if options.use_resource_graph:
        catalog = fetch_schedule_catalog(
            client,
            target_subs if target_subs else None,
            api_version=options.resource_graph_api,
        )

    # Also check AKS agentPoolProfiles for any legacy node pools that have no backing VMSS in raw_rows
    for pool in catalog.aks_pools:
        if allowed_subs is not None and pool.subscription_id not in allowed_subs:
            continue
        sku_info = classify_vm_sku(pool.vm_size)
        if sku_info is None or sku_info.generation.lower() not in allowed_gens:
            continue
        # Check if a backing VMSS in the nodeResourceGroup already represents this pool
        already_present = any(
            sub_id == pool.subscription_id
            and str(r.get("resourceGroup") or "").strip().lower() == pool.node_resource_group
            and (
                str((r.get("tags") or {}).get("aks-managed-poolName") or "").strip().lower() == pool.pool_name.lower()
                or pool.pool_name.lower() in str(r.get("name") or "").strip().lower()
            )
            for r, _, _, sub_id, _ in candidates
        )
        if not already_present and options.include_vmss:
            synth_id = f"{pool.cluster_id}/agentPools/{pool.pool_name}"
            synth_row: Dict[str, Any] = {
                "id": synth_id,
                "name": f"{pool.cluster_name}/{pool.pool_name}",
                "type": "Microsoft.ContainerService/managedClusters",
                "subscriptionId": pool.subscription_id,
                "resourceGroup": pool.resource_group,
                "location": pool.location,
                "skuName": pool.vm_size,
                "skuCapacity": pool.count,
                "osType": pool.os_type,
                "powerState": f"PowerState/{pool.power_state.lower()}",
                "tags": {"aks-managed-poolName": pool.pool_name},
            }
            candidates.append((synth_row, sku_info, True, pool.subscription_id, pool.count))

    usage_by_rid: Dict[str, ActualVmUsage] = {}
    if candidates and options.cost_source != COST_SOURCE_RETAIL:
        cm_client = ArmClient(
            token_key, tokens, endpoint, transport,
            timeout=min(options.timeout, 30.0), max_retries=2, **extra,
        )
        # Query subscriptions with the largest active legacy vCPU footprint first so the highest-spend
        # subscriptions always get Cost Management actuals before any tenant QPU burst limit is reached.
        sub_vcpus: Dict[str, int] = {}
        for row, sku_info, is_vmss, sub_id, capacity in candidates:
            pstate = normalise_power_state(row.get("powerState"), capacity=capacity if is_vmss else None)
            weight = sku_info.vcpus * max(1, capacity) * (10 if pstate != "Deallocated" else 1)
            sub_vcpus[sub_id] = sub_vcpus.get(sub_id, 0) + weight

        ordered_subs = sorted(subs_with_legacy.keys(), key=lambda s: (-sub_vcpus.get(s, 0), s))
        # Azure Cost Management enforces a ~15-20 request burst bucket per client/tenant before returning 429.
        # In 'auto' mode, prioritise the top 15 active subscriptions (which typically cover >98% of spend)
        # unless the user explicitly filtered subscriptions via --subscription.
        if options.cost_source == COST_SOURCE_AUTO and not options.subscription_filter and len(ordered_subs) > 15:
            ordered_subs = ordered_subs[:15]
        throttled_subs: List[str] = []
        for sub_id in ordered_subs:
            rids = subs_with_legacy[sub_id]
            data.cost_management_subs_queried += 1
            sub_usage, warn = fetch_subscription_actual_costs(
                cm_client,
                sub_id,
                rids,
                window,
                api_version=options.cost_management_api,
            )
            if warn:
                if "429" in warn or "TooManyRequests" in warn or "throttled" in warn.lower():
                    throttled_subs.append(names.subscription_label(sub_id))
                    remaining = [
                        names.subscription_label(s)
                        for s in ordered_subs[ordered_subs.index(sub_id) + 1:]
                    ]
                    throttled_subs.extend(remaining)
                    break
                data.issues.append(Issue(
                    LEVEL_INFO,
                    "cost-management",
                    f"{warn}; using Retail API rates for {names.subscription_label(sub_id)}.",
                ))
            else:
                data.cost_management_subs_succeeded += 1
                usage_by_rid.update(sub_usage)

        if throttled_subs:
            data.issues.append(Issue(
                LEVEL_INFO,
                "cost-management",
                f"Cost Management rate-limited after {data.cost_management_subs_succeeded} top subscription(s); "
                f"using Retail API rates for the remaining {len(throttled_subs)} smaller subscription(s).",
            ))

    for row, sku_info, is_vmss, sub_id, capacity in candidates:
        rid = str(row.get("id") or "")
        rtype_raw = str(row.get("type") or "")
        rname = str(row.get("name") or "")
        rg_name = str(row.get("resourceGroup") or "")
        region = str(row.get("location") or "uksouth").strip().lower()
        os_type = normalise_os_type(row.get("osType"), row.get("licenseType"))
        license_type = str(row.get("licenseType") or "").strip()
        priority = normalise_priority(row.get("priority"))
        power_state = normalise_power_state(row.get("powerState"), capacity=capacity if is_vmss else None)
        tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
        sched_info = catalog.by_resource_id.get(rid.lower())

        deployment_kind, schedule_summary, inferred_hours = infer_workload_and_schedule(
            resource_type_raw=rtype_raw,
            name=rname,
            resource_group=rg_name,
            subscription_id=sub_id,
            tags=tags,
            schedule_info=sched_info,
            aks_pools_by_key=catalog.aks_pools_by_key,
            default_hours=options.hours_per_month,
        )

        quote = pricing.quote(
            sku_info,
            region,
            os_type=os_type,
            license_type=license_type,
            priority=priority,
        )
        record = build_legacy_record(
            resource_id=rid,
            name=rname,
            resource_type=TYPE_VMSS if is_vmss else TYPE_VM,
            tenant_id=data.spec.tenant_id,
            tenant_name=data.display_name,
            subscription_id=sub_id,
            subscription_name=names.subscription_label(sub_id),
            resource_group=rg_name,
            region=region,
            sku_info=sku_info,
            instance_count=capacity,
            os_type=os_type,
            license_type=license_type,
            priority=priority,
            power_state=power_state,
            quote=quote,
            policy=policy,
            hours_per_month=options.hours_per_month,
            include_deallocated_cost=options.include_deallocated_cost,
            cost_source=options.cost_source,
            actual_usage=usage_by_rid.get(rid.lower()),
            schedule_info=sched_info,
            deployment_kind=deployment_kind,
            schedule_summary=schedule_summary,
            inferred_hours_per_month=inferred_hours,
        )
        data.records.append(record)

    data.records.sort(
        key=lambda r: (
            -r.monthly_delta,
            -r.current_monthly,
            -r.provisioned_current_monthly,
            r.generation,
            r.sku,
            r.subscription_name.lower(),
            r.name.lower(),
        )
    )
    return data


def _safe_int(value: Any, *, default: int = 1) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _collect_names(client: ArmClient, data: TenantData, options: CollectOptions) -> NameMaps:
    names = NameMaps(tenant_name=data.spec.name)
    try:
        for entry in client.list_all("/tenants", options.tenants_api):
            tid = str(entry.get("tenantId") or "").strip().lower()
            if tid == data.spec.tenant_id.lower():
                names.tenant_name = names.tenant_name or str(entry.get("displayName") or "").strip()
                names.default_domain = str(entry.get("defaultDomain") or "").strip()
                break
    except ArmError as exc:
        log.debug("Could not read /tenants for %s: %s", data.spec.tenant_id, exc)

    if names.tenant_name:
        data.display_name = names.tenant_name
    if names.default_domain:
        data.default_domain = names.default_domain

    try:
        subs = client.list_all("/subscriptions", options.subscriptions_api)
        for sub in subs:
            sid = str(sub.get("subscriptionId") or "").strip().lower()
            sname = str(sub.get("displayName") or "").strip()
            if is_guid(sid):
                names.subscriptions[sid] = sname or sid
        data.subscription_count = len(names.subscriptions)
    except ArmError as exc:
        data.issues.append(Issue(
            LEVEL_WARNING, "subscriptions",
            f"Could not list subscriptions ({exc}); subscription IDs will be shown instead of names."
        ))
    return names


def _resolve_target_subscriptions(
    data: TenantData, names: NameMaps, explicit: Sequence[str]
) -> List[str]:
    if explicit:
        missing = [s for s in explicit if names.subscriptions and s.lower() not in names.subscriptions]
        if missing:
            data.issues.append(Issue(
                LEVEL_WARNING, "subscriptions",
                f"Subscription filter includes ID(s) not returned by /subscriptions: {', '.join(missing)}"
            ))
        return [s.lower() for s in explicit]
    return list(names.subscriptions.keys())


def _try_resource_graph(
    client: ArmClient,
    data: TenantData,
    target_subs: Sequence[str],
    options: CollectOptions,
) -> Optional[List[Dict[str, Any]]]:
    try:
        rows = client.query_resource_graph(
            ARG_VM_QUERY,
            subscriptions=target_subs if target_subs else None,
            api_version=options.resource_graph_api,
        )
        data.discovery_method = "Azure Resource Graph"
        return rows
    except ArmError as exc:
        log.debug("Resource Graph query failed for %s: %s", data.spec.tenant_id, exc)
        data.issues.append(Issue(
            LEVEL_INFO, "resource-graph",
            f"Azure Resource Graph was unavailable ({exc}); falling back to per-subscription Compute API."
        ))
        return None


def _collect_via_compute_arm(
    client: ArmClient,
    data: TenantData,
    names: NameMaps,
    target_subs: Sequence[str],
    options: CollectOptions,
) -> Optional[List[Dict[str, Any]]]:
    subs = list(target_subs) or ([data.spec.subscription_hint] if is_guid(data.spec.subscription_hint) else [])
    if not subs:
        data.issues.append(Issue(
            LEVEL_ERROR, "compute",
            "No visible subscriptions were found to scan via the Compute API."
        ))
        return None

    rows: List[Dict[str, Any]] = []
    any_ok = False
    for sub_id in subs:
        try:
            vms = client.list_all(
                f"/subscriptions/{sub_id}/providers/Microsoft.Compute/virtualMachines",
                options.compute_api,
                params={"$expand": "instanceView"},
            )
            any_ok = True
            for vm in vms:
                rows.append(_normalise_arm_vm(vm, sub_id))
        except ArmError as exc:
            hint = " (Reader access is required on the subscription)" if exc.kind == KIND_PERMISSION else ""
            data.issues.append(Issue(
                LEVEL_WARNING, "compute",
                f"Could not list VMs in subscription {names.subscription_label(sub_id)}: {exc}{hint}"
            ))
            continue

        if options.include_vmss:
            try:
                vmss_list = client.list_all(
                    f"/subscriptions/{sub_id}/providers/Microsoft.Compute/virtualMachineScaleSets",
                    options.compute_api,
                )
                for vmss in vmss_list:
                    rows.append(_normalise_arm_vmss(vmss, sub_id))
            except ArmError as exc:
                data.issues.append(Issue(
                    LEVEL_WARNING, "compute-vmss",
                    f"Could not list VM scale sets in subscription {names.subscription_label(sub_id)}: {exc}"
                ))

    if not any_ok:
        data.issues.append(Issue(
            LEVEL_ERROR, "compute",
            "Could not list virtual machines in any subscription for this tenant."
        ))
        return None
    data.discovery_method = "ARM Microsoft.Compute API"
    return rows


def _resource_group_from_id(resource_id: str) -> str:
    parts = resource_id.split("/")
    for idx, token in enumerate(parts):
        if token.lower() == "resourcegroups" and idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _normalise_arm_vm(vm: Mapping[str, Any], sub_id: str) -> Dict[str, Any]:
    rid = str(vm.get("id") or "")
    props = vm.get("properties") if isinstance(vm.get("properties"), dict) else {}
    hw = props.get("hardwareProfile") if isinstance(props.get("hardwareProfile"), dict) else {}
    storage = props.get("storageProfile") if isinstance(props.get("storageProfile"), dict) else {}
    os_disk = storage.get("osDisk") if isinstance(storage.get("osDisk"), dict) else {}
    iview = props.get("instanceView") if isinstance(props.get("instanceView"), dict) else {}
    statuses = iview.get("statuses") if isinstance(iview.get("statuses"), list) else []
    power_code = ""
    for st in statuses:
        if isinstance(st, dict) and str(st.get("code") or "").lower().startswith("powerstate/"):
            power_code = str(st.get("code"))
            break
    return {
        "id": rid,
        "name": str(vm.get("name") or ""),
        "type": "Microsoft.Compute/virtualMachines",
        "subscriptionId": sub_id,
        "resourceGroup": _resource_group_from_id(rid),
        "location": str(vm.get("location") or ""),
        "tags": vm.get("tags") if isinstance(vm.get("tags"), dict) else {},
        "vmSize": str(hw.get("vmSize") or ""),
        "osType": str(os_disk.get("osType") or ""),
        "licenseType": str(props.get("licenseType") or ""),
        "priority": str(props.get("priority") or ""),
        "powerState": power_code,
    }


def _normalise_arm_vmss(vmss: Mapping[str, Any], sub_id: str) -> Dict[str, Any]:
    rid = str(vmss.get("id") or "")
    sku = vmss.get("sku") if isinstance(vmss.get("sku"), dict) else {}
    props = vmss.get("properties") if isinstance(vmss.get("properties"), dict) else {}
    vmp = props.get("virtualMachineProfile") if isinstance(props.get("virtualMachineProfile"), dict) else {}
    storage = vmp.get("storageProfile") if isinstance(vmp.get("storageProfile"), dict) else {}
    os_disk = storage.get("osDisk") if isinstance(storage.get("osDisk"), dict) else {}
    return {
        "id": rid,
        "name": str(vmss.get("name") or ""),
        "type": "Microsoft.Compute/virtualMachineScaleSets",
        "subscriptionId": sub_id,
        "resourceGroup": _resource_group_from_id(rid),
        "location": str(vmss.get("location") or ""),
        "tags": vmss.get("tags") if isinstance(vmss.get("tags"), dict) else {},
        "skuName": str(sku.get("name") or ""),
        "skuCapacity": sku.get("capacity", 0),
        "osType": str(os_disk.get("osType") or ""),
        "licenseType": str(vmp.get("licenseType") or ""),
        "priority": str(vmp.get("priority") or ""),
        "powerState": "PowerState/running" if _safe_int(sku.get("capacity"), default=0) > 0 else "PowerState/deallocated",
    }


def merge_repeats(results: Sequence[TenantData]) -> Tuple[List[TenantData], List[TenantData]]:
    """Keep one result per tenant GUID so duplicate specs never double-count VMs."""
    kept: Dict[str, TenantData] = {}
    order: List[str] = []
    dropped: List[TenantData] = []
    for item in results:
        key = item.spec.tenant_id.lower()
        if key not in kept:
            kept[key] = item
            order.append(key)
        else:
            dropped.append(item)
            if not kept[key].fatal and item.fatal:
                continue
            if kept[key].fatal and not item.fatal:
                kept[key] = item
    return [kept[key] for key in order], dropped
