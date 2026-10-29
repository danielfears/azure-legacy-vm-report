"""Access-token providers: Azure CLI (default) and service principal (client secret)."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional

from .transport import Transport, TransportError

GUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_GUID = re.compile(rf"^{GUID_PATTERN}$")
_TENANT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")

LOGIN_HINT = (
    "Sign in with 'az login --use-device-code --allow-no-subscriptions' (no --tenant: your account "
    "resolves its own home tenant). Add --tenant <id> only for a guest tenant whose id you were given."
)
WSL_HINT = (
    "If this is WSL and Windows sends Microsoft sign-in through a client such as Global Secure Access, the "
    "Linux Azure CLI cannot sign in: use the Windows Azure CLI through ./azure-legacy-vm-report-windows (see the README)."
)
WSL_HELPER_ENV = "AZURE_LEGACY_VM_REPORT_WSL_HELPER"
_UNREACHABLE = re.compile(
    r"login\.microsoftonline|max retries|connect ?timeout|connection ?error|timed out|failed to establish"
    r"|name or service not known|temporary failure in name resolution", re.IGNORECASE)
_TENANT_ARG = re.compile(r'--tenant\s+"?([A-Za-z0-9][A-Za-z0-9.-]*)"?')


class AuthError(Exception):
    """An access token could not be obtained."""


def is_guid(value: str) -> bool:
    return bool(_GUID.match(value or ""))


def validate_tenant(value: str) -> str:
    """Accept a tenant GUID or domain; reject anything that could be read as an option."""
    text = (value or "").strip()
    if not _TENANT.match(text):
        raise ValueError(f"Invalid tenant identifier {value!r}. Use the tenant GUID or its domain name.")
    return text


def find_az(windows: Optional[bool] = None) -> Optional[str]:
    """Locate the Azure CLI on PATH (absolute entries only on Windows)."""
    if not (os.name == "nt" if windows is None else windows):
        return shutil.which("az")
    extensions = [item for item in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if item]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        folder = entry.strip().strip('"')
        if not folder or not os.path.isabs(folder):
            continue
        for extension in extensions:
            candidate = os.path.join(folder, "az" + extension)
            if os.path.isfile(candidate):
                return candidate
    return None


def kill_windows_tree(process: "subprocess.Popen[str]") -> None:
    """Kill a process and its children on Windows."""
    taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
    try:
        subprocess.run(
            [taskkill, "/T", "/F", "/PID", str(process.pid)], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    process.kill()


def tenant_from_jwt(token: str) -> str:
    """The ``tid`` claim of an access token, or '' if it cannot be read."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode((payload + "=" * (-len(payload) % 4)).encode("ascii")))
    except (AttributeError, IndexError, ValueError):
        return ""
    tid = claims.get("tid") if isinstance(claims, dict) else None
    return tid.lower() if isinstance(tid, str) and is_guid(tid) else ""


@dataclass(frozen=True)
class AccessToken:
    token: str = field(repr=False)
    expires_on: float
    tenant_id: str = ""

    def is_fresh(self, now: float, skew: float = 300.0) -> bool:
        return self.expires_on - skew > now


class TokenProvider:
    def get_token(self, tenant_id: str) -> AccessToken:
        raise NotImplementedError

    def invalidate(self, tenant_id: str) -> None:
        """Forget any cached token for the tenant (called after an HTTP 401)."""


class RoutingTokenProvider(TokenProvider):
    """Send per-tenant overrides (for example service principals) to their own provider."""

    def __init__(self, default: TokenProvider, overrides: Optional[Mapping[str, TokenProvider]] = None) -> None:
        self._default = default
        self._overrides = {key.lower(): value for key, value in (overrides or {}).items()}

    def _for(self, tenant_id: str) -> TokenProvider:
        return self._overrides.get(tenant_id.lower(), self._default)

    def get_token(self, tenant_id: str) -> AccessToken:
        return self._for(tenant_id).get_token(tenant_id)

    def invalidate(self, tenant_id: str) -> None:
        self._for(tenant_id).invalidate(tenant_id)


class AzCli:
    """Runs the Azure CLI with a hard timeout."""

    def __init__(self, executable: Optional[str] = None, timeout: float = 90.0,
                 env: Optional[Mapping[str, str]] = None) -> None:
        self._exe = executable or find_az()
        self._timeout = timeout
        self._lock = threading.Lock()
        self._running: "Optional[subprocess.Popen[str]]" = None
        self._env = dict(os.environ if env is None else env)
        self._env["AZURE_CORE_NO_COLOR"] = "true"
        self._env["AZURE_CORE_ONLY_SHOW_ERRORS"] = "true"

    @property
    def available(self) -> bool:
        return self._exe is not None

    def run_json(self, args: List[str]) -> Any:
        if not self._exe:
            raise AuthError(
                "The Azure CLI ('az') was not found on PATH. Install it (https://aka.ms/installazurecli) "
                "or configure service principals with --config."
            )
        command = [self._exe, *args, "--output", "json"]
        with self._lock:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=self._env, start_new_session=True,
            )
            self._running = process
            try:
                out, err = process.communicate(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                self._kill(process)
                raise AuthError(
                    f"The Azure CLI did not respond within {self._timeout:.0f}s. Check connectivity to the Microsoft "
                    "sign-in endpoints (login.microsoftonline.com) and that your 'az login' session is still valid."
                    + self._wsl_hint()
                ) from None
            except BaseException:
                self._kill(process)
                raise
            finally:
                self._running = None
        if process.returncode != 0:
            raise AuthError(self._explain(err))
        try:
            return json.loads(out)
        except ValueError:
            raise AuthError("The Azure CLI returned output that is not valid JSON.") from None

    def abort(self) -> None:
        process = self._running
        if process is not None:
            self._signal_group(process)

    @staticmethod
    def _signal_group(process: "subprocess.Popen[str]") -> None:
        try:
            if hasattr(os, "killpg"):
                os.killpg(process.pid, signal.SIGKILL)
            else:  # pragma: no cover
                kill_windows_tree(process)
        except OSError:
            pass

    @classmethod
    def _kill(cls, process: "subprocess.Popen[str]") -> None:
        cls._signal_group(process)
        try:
            process.communicate(timeout=5)
        except Exception:  # noqa: BLE001
            pass

    def _wsl_hint(self) -> str:
        return f" {WSL_HINT}" if self._env.get("WSL_DISTRO_NAME") else ""

    def _explain(self, stderr: str) -> str:
        lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
        first = (lines[0] if lines else "the Azure CLI reported an error")[:300]
        suggested = next((line for line in lines[1:] if line.startswith("az login ")), "")
        if suggested:
            helper, tenant = self._env.get(WSL_HELPER_ENV), _TENANT_ARG.search(suggested)
            if helper and tenant:
                return f"{first} Sign in again from WSL with: {helper} login {tenant.group(1)}"
            return f"{first} Sign in again with: {suggested[:300]} (add --use-device-code if no browser opens)"
        return f"{first} {LOGIN_HINT}{self._wsl_hint() if _UNREACHABLE.search(stderr or '') else ''}"


class AzCliTokenProvider(TokenProvider):
    """Mint ARM tokens with ``az account get-access-token`` and cache them in memory."""

    def __init__(self, az: AzCli, resource: str, hints: Optional[Mapping[str, str]] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._az = az
        self._resource = resource
        self._hints = {key.lower(): value for key, value in (hints or {}).items()}
        self._clock = clock
        self._cache: Dict[str, AccessToken] = {}
        self._lock = threading.Lock()

    def add_hint(self, tenant_id: str, subscription_id: str) -> None:
        if is_guid(subscription_id):
            self._hints.setdefault(tenant_id.lower(), subscription_id)

    def get_token(self, tenant_id: str) -> AccessToken:
        tenant = validate_tenant(tenant_id)
        key = tenant.lower()
        with self._lock:
            cached = self._cache.get(key)
        if cached and cached.is_fresh(self._clock()):
            return cached

        args = ["account", "get-access-token", "--resource", self._resource]
        hint = self._hints.get(key)
        args += ["--subscription", hint] if hint and is_guid(hint) else ["--tenant", tenant]
        try:
            data = self._az.run_json(args)
        except AuthError as exc:
            raise AuthError(f"Could not get a token for tenant {tenant}: {exc}") from None

        token = data.get("accessToken") if isinstance(data, dict) else None
        if not token:
            raise AuthError(f"The Azure CLI returned no access token for tenant {tenant}.")
        returned = str(data.get("tenant") or "")
        if is_guid(tenant) and is_guid(returned) and returned.lower() != key:
            raise AuthError(
                f"The Azure CLI issued a token for tenant {returned}, not the requested {tenant}. "
                "Check the subscription hint for this tenant."
            )
        fresh = AccessToken(
            token=token, expires_on=self._expiry(data),
            tenant_id=returned.lower() if is_guid(returned) else tenant_from_jwt(token),
        )
        with self._lock:
            self._cache[key] = fresh
        return fresh

    def invalidate(self, tenant_id: str) -> None:
        with self._lock:
            self._cache.pop(tenant_id.lower(), None)

    def _expiry(self, data: Mapping[str, Any]) -> float:
        epoch = data.get("expires_on")
        if isinstance(epoch, (int, float)):
            return float(epoch)
        try:
            return datetime.strptime(str(data.get("expiresOn")), "%Y-%m-%d %H:%M:%S.%f").timestamp()
        except ValueError:
            return self._clock() + 20 * 60


@dataclass(frozen=True)
class SpCredential:
    client_id: str
    secret_env: str


def _without_secret(text: str, secret: str) -> str:
    for form in {secret, urllib.parse.quote_plus(secret)}:
        if form:
            text = text.replace(form, "[secret removed]")
    return text


class ServicePrincipalTokenProvider(TokenProvider):
    """Client-credentials flow; the secret is read from an environment variable only."""

    def __init__(self, credentials: Mapping[str, SpCredential], transport: Transport, *, authority_host: str,
                 scope: str, env: Optional[Mapping[str, str]] = None, timeout: float = 30.0,
                 clock: Callable[[], float] = time.time) -> None:
        self._credentials = {key.lower(): value for key, value in credentials.items()}
        self._transport = transport
        self._authority = authority_host
        self._scope = scope
        self._env = os.environ if env is None else env
        self._timeout = timeout
        self._clock = clock
        self._cache: Dict[str, AccessToken] = {}
        self._lock = threading.Lock()

    def get_token(self, tenant_id: str) -> AccessToken:
        key = tenant_id.lower()
        credential = self._credentials.get(key)
        if credential is None:
            raise AuthError(f"No service principal is configured for tenant {tenant_id}.")
        with self._lock:
            cached = self._cache.get(key)
        if cached and cached.is_fresh(self._clock()):
            return cached

        secret = self._env.get(credential.secret_env, "")
        if not secret:
            raise AuthError(
                f"Environment variable {credential.secret_env} (client secret for tenant {tenant_id}) is not set."
            )
        authority = self._authority.rstrip("/")
        if not authority.lower().startswith("https://"):
            raise AuthError("The authority host must use https.")
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": credential.client_id,
            "client_secret": secret,
            "scope": self._scope,
        }).encode("ascii")
        url = f"{authority}/{urllib.parse.quote(tenant_id)}/oauth2/v2.0/token"
        try:
            response = self._transport.request(
                "POST", url,
                {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                body, self._timeout,
            )
        except TransportError as exc:
            raise AuthError(
                f"Service principal sign-in failed for tenant {tenant_id}: {_without_secret(str(exc), secret)}"
            ) from None

        try:
            payload = json.loads(response.body.decode("utf-8") or "{}")
        except ValueError:
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        if response.status != 200 or not payload.get("access_token"):
            detail = _without_secret(
                str(payload.get("error_description") or payload.get("error") or "no detail returned"), secret)
            raise AuthError(
                f"Service principal sign-in failed for tenant {tenant_id} (HTTP {response.status}): "
                f"{detail.splitlines()[0][:300]}"
            )
        try:
            lifetime = int(payload.get("expires_in") or 3600)
        except (TypeError, ValueError):
            lifetime = 3600
        fresh = AccessToken(
            token=payload["access_token"], expires_on=self._clock() + lifetime,
            tenant_id=tenant_from_jwt(payload["access_token"]),
        )
        with self._lock:
            self._cache[key] = fresh
        return fresh

    def invalidate(self, tenant_id: str) -> None:
        with self._lock:
            self._cache.pop(tenant_id.lower(), None)
