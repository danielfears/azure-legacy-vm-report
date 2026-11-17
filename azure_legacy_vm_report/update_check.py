"""Non-blocking, fail-open check for newer GitHub releases with a 24-hour local cache."""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple

from .transport import Transport, TransportError

REPO_URL = "https://github.com/danielfears/azure-legacy-vm-report"
RELEASES_URL = f"{REPO_URL}/releases"
LATEST_RELEASE_API = "https://api.github.com/repos/danielfears/azure-legacy-vm-report/releases/latest"
NO_UPDATE_CHECK_ENV = "AZURE_LEGACY_VM_REPORT_NO_UPDATE_CHECK"
CACHE_TTL_SECONDS = 86_400.0
DEFAULT_CHECK_TIMEOUT = 2.5

_SEMVER_RE = re.compile(r"^v?(?P<maj>\d+)\.(?P<min>\d+)\.(?P<pat>\d+)$")


@dataclass(frozen=True)
class UpdateNotice:
    current_version: str
    latest_version: str
    release_url: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "release_url": self.release_url,
        }


def parse_semver(version_text: str) -> Optional[Tuple[int, int, int]]:
    """Parse a stable ``X.Y.Z`` or ``vX.Y.Z`` version into an integer tuple; reject pre-releases."""
    match = _SEMVER_RE.match((version_text or "").strip())
    if not match:
        return None
    return int(match.group("maj")), int(match.group("min")), int(match.group("pat"))


def _safe_release_url(candidate_url: str, latest_version: str) -> str:
    text = (candidate_url or "").strip()
    if text.startswith(f"{REPO_URL}/"):
        return text
    return f"{RELEASES_URL}/tag/v{latest_version}"


def default_cache_path(env: Optional[Mapping[str, str]] = None) -> Path:
    environ = os.environ if env is None else env
    if os.name == "nt":
        base = Path(environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return base / "azure-legacy-vm-report" / "update-check.json"


def _read_cached(cache_path: Optional[Path], now: float, ttl: float) -> Optional[Tuple[str, str]]:
    if cache_path is None:
        return None
    with contextlib.suppress(OSError, ValueError, TypeError):
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        checked_at = float(raw.get("checked_at") or 0.0)
        latest = str(raw.get("latest_version") or "").strip().lstrip("vV")
        url = str(raw.get("release_url") or "").strip()
        if latest and (now - checked_at) < ttl and parse_semver(latest) is not None:
            return latest, _safe_release_url(url, latest)
    return None


def _write_cached(cache_path: Optional[Path], now: float, latest_version: str, release_url: str) -> None:
    if cache_path is None:
        return
    with contextlib.suppress(OSError):
        cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(
            {
                "checked_at": round(now, 1),
                "latest_version": latest_version,
                "release_url": release_url,
            }
        )
        cache_path.write_text(payload + "\n", encoding="utf-8")


def is_update_check_disabled(
    *,
    disabled_flag: bool = False,
    demo: bool = False,
    offline_prices: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    if disabled_flag or demo or offline_prices:
        return True
    environ = os.environ if env is None else env
    raw_env = (environ.get(NO_UPDATE_CHECK_ENV) or "").strip().lower()
    return raw_env in ("1", "true", "yes", "on")


def check_for_update(
    current_version: str,
    transport: Transport,
    *,
    cache_path: Optional[Path] = None,
    ttl_seconds: float = CACHE_TTL_SECONDS,
    timeout: float = DEFAULT_CHECK_TIMEOUT,
    clock: Callable[[], float] = time.time,
) -> Optional[UpdateNotice]:
    """Return an ``UpdateNotice`` if a newer stable GitHub release exists; fail silently on any error."""
    cur_clean = (current_version or "").strip().lstrip("vV")
    cur_tuple = parse_semver(cur_clean)
    if cur_tuple is None:
        return None

    now = clock()
    cached = _read_cached(cache_path, now, ttl_seconds)
    if cached is not None:
        latest_ver, rel_url = cached
        latest_tuple = parse_semver(latest_ver)
        if latest_tuple is not None and latest_tuple > cur_tuple:
            return UpdateNotice(current_version=cur_clean, latest_version=latest_ver, release_url=rel_url)
        return None

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"azure-legacy-vm-report/{cur_clean}",
    }
    try:
        resp = transport.request("GET", LATEST_RELEASE_API, headers, None, timeout)
    except (TransportError, OSError):
        return None

    if resp.status != 200:
        return None
    try:
        payload = json.loads(resp.body.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None

    raw_tag = str(payload.get("tag_name") or "").strip()
    latest_clean = raw_tag.lstrip("vV")
    latest_tuple = parse_semver(latest_clean)
    if latest_tuple is None:
        return None

    rel_url = _safe_release_url(str(payload.get("html_url") or ""), latest_clean)
    _write_cached(cache_path, now, latest_clean, rel_url)

    if latest_tuple > cur_tuple:
        return UpdateNotice(current_version=cur_clean, latest_version=latest_clean, release_url=rel_url)
    return None
