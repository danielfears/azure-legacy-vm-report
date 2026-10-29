"""Minimal Azure Resource Manager client: paging, Resource Graph queries, retries and safe error mapping."""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import __version__
from .auth import AuthError, TokenProvider
from .transport import Transport, TransportError

log = logging.getLogger("azure_legacy_vm_report.arm")

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 30.0
MAX_RETRY_AFTER_SECONDS = 120.0
DEFAULT_MAX_PAGES = 500
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
USER_AGENT = f"azure-legacy-vm-report/{__version__}"

KIND_PERMISSION = "permission"
KIND_AUTH = "auth"
KIND_NOT_FOUND = "not_found"
KIND_THROTTLED = "throttled"
KIND_NETWORK = "network"
KIND_BAD_RESPONSE = "bad_response"
KIND_OTHER = "error"


class ArmError(Exception):
    """A call to Azure Resource Manager failed."""

    def __init__(self, message: str, *, status: Optional[int] = None, code: str = "",
                 kind: str = KIND_OTHER, detail: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.kind = kind
        self.detail = detail


def _origin(url: str) -> Tuple[str, str, int]:
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    port = parts.port or {"https": 443, "http": 80}.get(scheme, 0)
    return scheme, (parts.hostname or "").lower(), port


def validate_endpoint(endpoint: str) -> str:
    """Require https (plain http only for loopback, which the offline tests use)."""
    text = (endpoint or "").strip().rstrip("/")
    scheme, host, _ = _origin(text)
    if not host or (scheme != "https" and not (scheme == "http" and host in LOOPBACK_HOSTS)):
        raise ValueError(f"The Azure Resource Manager endpoint {endpoint!r} must be an https URL.")
    return text


_COST_MANAGEMENT_RETRY_HEADERS = (
    "x-ms-ratelimit-microsoft.costmanagement-clienttype-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after",
    "x-ms-ratelimit-microsoft.consumption-retry-after",
    "retry-after",
)


def _retry_delay_from_headers(headers: Mapping[str, str], attempt: int) -> float:
    delays: List[float] = []
    for name in _COST_MANAGEMENT_RETRY_HEADERS:
        raw = headers.get(name)
        if not raw:
            continue
        try:
            delays.append(max(0.0, float(raw)))
        except ValueError:
            pass
    if delays:
        return min(MAX_RETRY_AFTER_SECONDS, max(delays))
    return min(MAX_BACKOFF_SECONDS, float(2 ** attempt))

def _one_line(text: str, limit: int = 300) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"



class ArmClient:
    """Reads from Azure Resource Manager on behalf of one tenant."""

    def __init__(
        self,
        tenant_id: str,
        tokens: TokenProvider,
        endpoint: str,
        transport: Transport,
        *,
        timeout: float = 60.0,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        self.tenant_id = tenant_id
        self._tokens = tokens
        self._endpoint = validate_endpoint(endpoint)
        self._origin = _origin(self._endpoint)
        self._transport = transport
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._sleep = sleep
        self._max_pages = max_pages

    def build_url(self, path: str, api_version: str, params: Optional[Mapping[str, str]] = None) -> str:
        query = {"api-version": api_version, **(params or {})}
        return f"{self._endpoint}{path}?{urllib.parse.urlencode(query)}"

    def get_json(self, path: str, api_version: str, params: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        return self._request("GET", self.build_url(path, api_version, params), None)

    def post_json(
        self,
        path: str,
        api_version: str,
        payload: Mapping[str, Any],
        params: Optional[Mapping[str, str]] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        return self._request("POST", self.build_url(path, api_version, params), body, extra_headers=extra_headers)

    def list_all(
        self, path: str, api_version: str, params: Optional[Mapping[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Follow ``nextLink`` until exhausted and return every item in ``value``."""
        url: Optional[str] = self.build_url(path, api_version, params)
        items: List[Dict[str, Any]] = []
        seen = set()
        for _ in range(self._max_pages):
            if url is None:
                return items
            if url in seen:
                raise ArmError("Azure returned a paging loop; stopping.", kind=KIND_BAD_RESPONSE)
            seen.add(url)
            page = self._request("GET", url, None)
            value = page.get("value")
            if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                raise ArmError(
                    "Azure Resource Manager returned a list in an unexpected shape.", kind=KIND_BAD_RESPONSE)
            items.extend(value)
            link = page.get("nextLink") or page.get("@nextLink") or page.get("@odata.nextLink")
            url = self._checked_link(link) if link else None
        if url is None:
            return items
        raise ArmError(f"Stopped after {self._max_pages} pages; the result set is unexpectedly large.",
                       kind=KIND_BAD_RESPONSE)

    def query_resource_graph(
        self,
        query: str,
        *,
        subscriptions: Optional[Sequence[str]] = None,
        api_version: str = "2022-10-01",
    ) -> List[Dict[str, Any]]:
        """Run a KQL query against Azure Resource Graph, following ``$skipToken`` until exhausted."""
        items: List[Dict[str, Any]] = []
        skip_token: Optional[str] = None
        seen_tokens = set()
        for _ in range(self._max_pages):
            options: Dict[str, Any] = {"resultFormat": "objectArray", "$top": 1000}
            if skip_token:
                if skip_token in seen_tokens:
                    raise ArmError("Azure Resource Graph returned a paging loop; stopping.", kind=KIND_BAD_RESPONSE)
                seen_tokens.add(skip_token)
                options["$skipToken"] = skip_token
            payload: Dict[str, Any] = {"query": query, "options": options}
            if subscriptions:
                payload["subscriptions"] = list(subscriptions)
            page = self.post_json("/providers/Microsoft.ResourceGraph/resources", api_version, payload)
            data = page.get("data")
            if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
                raise ArmError(
                    "Azure Resource Graph returned data in an unexpected shape.", kind=KIND_BAD_RESPONSE)
            items.extend(data)
            next_token = page.get("$skipToken") or page.get("skipToken")
            if not next_token:
                return items
            skip_token = str(next_token)
        raise ArmError(f"Stopped after {self._max_pages} Resource Graph pages; the result set is unexpectedly large.",
                       kind=KIND_BAD_RESPONSE)

    def _checked_link(self, link: Any) -> str:
        text = str(link)
        if _origin(text) != self._origin:
            host = urllib.parse.urlsplit(text).hostname or "unknown host"
            raise ArmError(
                f"Refusing to follow a paging link to a different host ({host}).", kind=KIND_BAD_RESPONSE,
            )
        return text

    def _pause(self, attempt: int, headers: Mapping[str, str]) -> None:
        delay = _retry_delay_from_headers(headers, attempt)
        log.debug("Retrying in %.1fs (attempt %d)", delay, attempt + 1)
        self._sleep(delay)

    def _request(
        self,
        method: str,
        url: str,
        body: Optional[bytes],
        *,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        refreshed = False
        attempt = 0
        while True:
            try:
                token = self._tokens.get_token(self.tenant_id)
            except AuthError as exc:
                raise ArmError(str(exc), kind=KIND_AUTH) from None
            headers = {
                "Authorization": f"Bearer {token.token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            }
            if body is not None:
                headers["Content-Type"] = "application/json"
            if extra_headers:
                headers.update(extra_headers)
            log.debug("%s %s", method, url)
            try:
                response = self._transport.request(method, url, headers, body, self._timeout)
            except TransportError as exc:
                if attempt < self._max_retries:
                    self._pause(attempt, {})
                    attempt += 1
                    continue
                raise ArmError(f"Network error calling Azure Resource Manager: {exc}", kind=KIND_NETWORK) from None

            status = response.status
            if 200 <= status < 300:
                return self._decode(response.body)
            if status == 401 and not refreshed:
                self._tokens.invalidate(self.tenant_id)
                refreshed = True
                continue
            if status in RETRYABLE_STATUS and attempt < self._max_retries:
                self._pause(attempt, response.headers)
                attempt += 1
                continue
            raise self._error(status, response.headers, response.body)

    @staticmethod
    def _decode(body: bytes) -> Dict[str, Any]:
        try:
            data = json.loads(body.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            raise ArmError("Azure Resource Manager returned a response that is not valid JSON.",
                           kind=KIND_BAD_RESPONSE) from None
        if not isinstance(data, dict):
            raise ArmError("Azure Resource Manager returned an unexpected response shape.", kind=KIND_BAD_RESPONSE)
        return data

    @staticmethod
    def _error(status: int, headers: Mapping[str, str], body: bytes) -> ArmError:
        code = message = ""
        try:
            payload = json.loads(body.decode("utf-8-sig"))
            inner = payload.get("error") if isinstance(payload, dict) else None
            source = inner if isinstance(inner, dict) else (payload if isinstance(payload, dict) else {})
            code = str(source.get("code") or "")
            message = str(source.get("message") or "")
        except (ValueError, UnicodeDecodeError, AttributeError):
            pass
        request_id = headers.get("x-ms-request-id") or headers.get("x-ms-correlation-request-id") or ""
        suffix = f" (request id {request_id})" if request_id else ""
        head = f"HTTP {status}{' ' + code if code else ''}"

        if status == 403:
            return ArmError(f"{head}: access denied{suffix}", status=status, code=code,
                            kind=KIND_PERMISSION, detail=_one_line(message))
        if status == 401:
            return ArmError(f"{head}: the token was rejected{suffix}", status=status, code=code,
                            kind=KIND_AUTH, detail=_one_line(message))
        kind = {404: KIND_NOT_FOUND, 429: KIND_THROTTLED}.get(status, KIND_OTHER)
        text = f"{head}: {_one_line(message)}{suffix}" if message else f"{head}{suffix}"
        return ArmError(text, status=status, code=code, kind=kind, detail=_one_line(message))
