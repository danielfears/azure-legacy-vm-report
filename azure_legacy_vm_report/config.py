"""Tenant selection: clouds, config-file parsing and Azure CLI discovery."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .auth import AuthError, AzCli, is_guid, validate_tenant

AUTH_AZ = "az"
AUTH_SP = "service-principal"
_AUTH_ALIASES = {
    "az": AUTH_AZ, "azure-cli": AUTH_AZ, "cli": AUTH_AZ,
    "service-principal": AUTH_SP, "serviceprincipal": AUTH_SP, "sp": AUTH_SP,
}
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_CONFIG_BYTES = 1_000_000


class ConfigError(Exception):
    """The configuration file or tenant selection is invalid."""


@dataclass(frozen=True)
class Cloud:
    name: str
    arm: str
    authority: str
    prices_api: str = "https://prices.azure.com/api/retail/prices"

    @property
    def arm_resource(self) -> str:
        return self.arm + "/"

    @property
    def arm_scope(self) -> str:
        return self.arm + "/.default"


CLOUDS: Dict[str, Cloud] = {
    "AzureCloud": Cloud("AzureCloud", "https://management.azure.com", "https://login.microsoftonline.com"),
    "AzureUSGovernment": Cloud(
        "AzureUSGovernment", "https://management.usgovcloudapi.net", "https://login.microsoftonline.us"),
    "AzureChinaCloud": Cloud(
        "AzureChinaCloud", "https://management.chinacloudapi.cn", "https://login.chinacloudapi.cn"),
}
DEFAULT_CLOUD = "AzureCloud"


@dataclass(frozen=True)
class TenantSpec:
    tenant_id: str
    name: str = ""
    auth: str = AUTH_AZ
    subscription_hint: str = ""
    client_id: str = ""
    secret_env: str = ""

    @property
    def label(self) -> str:
        return self.name or self.tenant_id


@dataclass
class LoadedConfig:
    tenants: List[TenantSpec] = field(default_factory=list)
    cloud: Optional[str] = None


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _tenant_id(value: Any, where: str) -> str:
    text = _clean(value)
    if not text:
        raise ConfigError(f"{where}: the tenant id is missing.")
    try:
        return validate_tenant(text)
    except ValueError as exc:
        raise ConfigError(f"{where}: {exc}") from None


def _hint(value: Any, where: str) -> str:
    text = _clean(value)
    if text.lower().startswith("/subscriptions/"):
        text = text.split("/")[2] if len(text.split("/")) > 2 else ""
    if text and not is_guid(text):
        raise ConfigError(f"{where}: subscriptionId must be a GUID.")
    return text.lower()


def _entry(raw: Any, index: int) -> TenantSpec:
    where = f"tenants[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: expected an object.")
    if any(key.lower() in ("clientsecret", "secret", "password") for key in raw):
        raise ConfigError(
            f"{where}: do not put secrets in the config file. Set 'clientSecretEnv' to the name of an "
            "environment variable that holds the client secret."
        )
    if any(key.lower() == "authorityhost" for key in raw):
        raise ConfigError(
            f"{where}: authorityHost is not supported. The sign-in endpoint is fixed by 'cloud' (or --cloud), so a "
            "config file cannot send a client secret to another host."
        )
    tenant = _tenant_id(raw.get("id") or raw.get("tenantId"), where)
    method = _AUTH_ALIASES.get(_clean(raw.get("auth") or AUTH_AZ).lower())
    if method is None:
        raise ConfigError(f"{where}: auth must be 'az' or 'service-principal'.")
    spec = dict(
        tenant_id=tenant,
        name=_clean(raw.get("name")),
        auth=method,
        subscription_hint=_hint(raw.get("subscriptionId"), where),
    )
    if method == AUTH_SP:
        client_id, env_name = _clean(raw.get("clientId")), _clean(raw.get("clientSecretEnv"))
        if not is_guid(client_id):
            raise ConfigError(f"{where}: clientId must be the application (client) id GUID.")
        if not _ENV_NAME.match(env_name):
            raise ConfigError(f"{where}: clientSecretEnv must name an environment variable, e.g. MY_TENANT_SECRET.")
        spec.update(client_id=client_id, secret_env=env_name)
    return TenantSpec(**spec)


def _from_subscriptions(items: Iterable[Any]) -> List[TenantSpec]:
    grouped: Dict[str, str] = {}
    for index, raw in enumerate(items):
        where = f"azure.subscriptions[{index}]"
        if not isinstance(raw, dict) or not raw.get("tenantId"):
            continue
        tenant = _tenant_id(raw.get("tenantId"), where)
        grouped.setdefault(tenant.lower(), "")
        hint = _hint(raw.get("id"), where) if raw.get("id") else ""
        if hint and not grouped[tenant.lower()]:
            grouped[tenant.lower()] = hint
    return [TenantSpec(tenant_id=tenant, subscription_hint=hint) for tenant, hint in grouped.items()]


def load_config(path: Path) -> LoadedConfig:
    try:
        size = path.stat().st_size
        if size > MAX_CONFIG_BYTES:
            raise ConfigError(f"{path}: the file is unexpectedly large ({size} bytes).")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc.strerror or exc}") from None
    except ValueError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: the top level must be a JSON object.")

    cloud = _clean(data.get("cloud")) or None
    if cloud and cloud not in CLOUDS:
        raise ConfigError(f"{path}: cloud must be one of {', '.join(CLOUDS)}.")

    tenants: List[TenantSpec]
    if isinstance(data.get("tenants"), list):
        tenants = [_entry(item, index) for index, item in enumerate(data["tenants"])]
    elif isinstance(data.get("azure"), dict) and isinstance(data["azure"].get("subscriptions"), list):
        tenants = _from_subscriptions(data["azure"]["subscriptions"])
    else:
        raise ConfigError(f"{path}: expected a 'tenants' array (see config.example.json).")
    if not tenants:
        raise ConfigError(f"{path}: no tenants are listed.")

    seen: Dict[str, int] = {}
    for index, spec in enumerate(tenants):
        key = spec.tenant_id.lower()
        if key in seen:
            raise ConfigError(f"{path}: tenant {spec.tenant_id} is listed more than once (entries {seen[key] + 1} "
                              f"and {index + 1}).")
        seen[key] = index
    return LoadedConfig(tenants=tenants, cloud=cloud)


def parse_tenant_args(values: Iterable[str]) -> List[TenantSpec]:
    specs: List[TenantSpec] = []
    seen = set()
    for value in values:
        for part in str(value).split(","):
            if not part.strip():
                continue
            try:
                tenant = validate_tenant(part)
            except ValueError as exc:
                raise ConfigError(str(exc)) from None
            if tenant.lower() not in seen:
                seen.add(tenant.lower())
                specs.append(TenantSpec(tenant_id=tenant))
    return specs


def parse_subscription_filter(values: Iterable[str]) -> List[str]:
    """Turn repeated/comma-separated ``--subscription`` GUIDs into a lower-case list."""
    subs: List[str] = []
    seen = set()
    for value in values:
        for part in str(value).split(","):
            text = part.strip()
            if not text:
                continue
            if not is_guid(text):
                raise ConfigError(f"Invalid subscription id {text!r}. Use a subscription GUID.")
            lower = text.lower()
            if lower not in seen:
                seen.add(lower)
                subs.append(lower)
    return subs


def _real_subscription(entry: Mapping[str, Any]) -> bool:
    sub_id = _clean(entry.get("id"))
    return is_guid(sub_id) and sub_id.lower() != _clean(entry.get("tenantId")).lower()


def _display_name(entry: Mapping[str, Any]) -> str:
    return _clean(entry.get("tenantDisplayName")) or _clean(entry.get("tenantDefaultDomain"))


def discover_az_tenants(az: AzCli) -> List[TenantSpec]:
    """Every tenant the Azure CLI session knows about (``az account list --all``)."""
    accounts = az.run_json(["account", "list", "--all"])
    if not isinstance(accounts, list):
        raise AuthError("The Azure CLI returned an unexpected account list.")
    tenants: Dict[str, Dict[str, str]] = {}
    for entry in accounts:
        if not isinstance(entry, dict) or not is_guid(_clean(entry.get("tenantId"))):
            continue
        tenant = _clean(entry.get("tenantId")).lower()
        info = tenants.setdefault(tenant, {"name": "", "hint": ""})
        info["name"] = info["name"] or _display_name(entry)
        if not info["hint"] and _real_subscription(entry) and _clean(entry.get("state")).lower() == "enabled":
            info["hint"] = _clean(entry.get("id")).lower()
    return [
        TenantSpec(tenant_id=tenant, name=info["name"], subscription_hint=info["hint"])
        for tenant, info in tenants.items()
    ]


def current_az_tenant(az: AzCli) -> TenantSpec:
    """The tenant of the active Azure CLI account."""
    entry = az.run_json(["account", "show"])
    if not isinstance(entry, dict) or not is_guid(_clean(entry.get("tenantId"))):
        raise AuthError("The Azure CLI did not report a current tenant.")
    return TenantSpec(
        tenant_id=_clean(entry["tenantId"]).lower(),
        name=_display_name(entry),
        subscription_hint=_clean(entry.get("id")).lower() if _real_subscription(entry) else "",
    )
