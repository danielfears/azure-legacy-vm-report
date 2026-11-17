"""Date parsing and formatting helpers."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Optional, Tuple
from zoneinfo import ZoneInfo

UTC = timezone.utc

_ISO = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"(?:[Tt ](?P<h>\d{2}):(?P<mi>\d{2})(?::(?P<s>\d{2})(?:[.,](?P<f>\d+))?)?)?"
    r"\s*(?P<tz>[Zz]|[+-]\d{2}(?::?\d{2})?)?$"
)


def _parse_offset(text: str) -> tzinfo:
    if text in ("Z", "z"):
        return UTC
    sign = -1 if text[0] == "-" else 1
    digits = text[1:].replace(":", "")
    hours = int(digits[:2])
    minutes = int(digits[2:4] or 0)
    if minutes > 59:
        raise ValueError("invalid UTC offset")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def parse_instant(
    value: Any,
    *,
    default_tz: tzinfo = UTC,
    date_only_end: bool = False,
) -> Optional[datetime]:
    """Parse an ISO 8601 date or timestamp into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=default_tz)
        return aware.astimezone(UTC)
    if isinstance(value, date):
        value = value.isoformat()
    match = _ISO.match(str(value).strip())
    if not match:
        return None
    parts = match.groupdict()
    try:
        if parts["h"] is None:
            clock = time(23, 59, 59, 999999) if date_only_end else time(0, 0, 0)
        else:
            fraction = int((parts["f"] or "0")[:6].ljust(6, "0"))
            clock = time(int(parts["h"]), int(parts["mi"]), int(parts["s"] or 0), fraction)
        day = date(int(parts["y"]), int(parts["mo"]), int(parts["d"]))
        zone = _parse_offset(parts["tz"]) if parts["tz"] else default_tz
        return datetime.combine(day, clock).replace(tzinfo=zone).astimezone(UTC)
    except (ValueError, OverflowError):
        return None


class _EuropeLondonTz(tzinfo):
    """Stdlib fallback for Europe/London (GMT/BST) on Windows Python without the tzdata package."""

    @staticmethod
    def _last_sunday(year: int, month: int) -> date:
        # March and October both have 31 days
        last_day = date(year, month, 31)
        offset = (last_day.weekday() + 1) % 7
        return last_day - timedelta(days=offset)

    @classmethod
    def _is_bst(cls, dt: Optional[datetime]) -> bool:
        if dt is None:
            return False
        # Convert wall/aware comparison cleanly via naive UTC or local transition rules:
        # BST runs from last Sunday in March 01:00 UTC to last Sunday in October 01:00 UTC.
        year = dt.year
        bst_start_utc = datetime.combine(cls._last_sunday(year, 3), time(1, 0), UTC)
        bst_end_utc = datetime.combine(cls._last_sunday(year, 10), time(1, 0), UTC)
        naive = dt.replace(tzinfo=None)
        start_local = datetime(bst_start_utc.year, 3, bst_start_utc.day, 2, 0)
        end_local = datetime(bst_end_utc.year, 10, bst_end_utc.day, 1, 0)
        if start_local <= naive < end_local:
            return True
        if end_local <= naive < end_local + timedelta(hours=1):
            return getattr(dt, "fold", 0) == 0
        return False

    def utcoffset(self, dt: Optional[datetime]) -> timedelta:
        return timedelta(hours=1) if self._is_bst(dt) else timedelta(0)

    def dst(self, dt: Optional[datetime]) -> timedelta:
        return timedelta(hours=1) if self._is_bst(dt) else timedelta(0)

    def tzname(self, dt: Optional[datetime]) -> str:
        return "BST" if self._is_bst(dt) else "GMT"


EUROPE_LONDON_FALLBACK = _EuropeLondonTz()


def resolve_timezone(name: str) -> Tuple[tzinfo, Optional[str]]:
    """Return a tzinfo for ``name`` plus a warning when it falls back to UTC."""
    cleaned = (name or "").strip()
    if cleaned.upper() in ("UTC", "GMT", "ETC/UTC", "ETC/GMT"):
        return UTC, None
    try:
        return ZoneInfo(cleaned), None
    except Exception:  # noqa: BLE001
        if cleaned.lower() in ("europe/london", "gb", "uk"):
            return EUROPE_LONDON_FALLBACK, None
        return UTC, f"Time zone '{name}' is not available on this system; using UTC."


def iso_utc(value: Optional[datetime]) -> str:
    """ISO 8601 UTC string for machine-readable output, or '' when missing."""
    if value is None:
        return ""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_date(value: Optional[datetime], tz: tzinfo) -> str:
    """DD/MM/YYYY in the report time zone, or an em dash when missing."""
    if value is None:
        return "\u2014"
    return value.astimezone(tz).strftime("%d/%m/%Y")


def format_datetime(value: Optional[datetime], tz: tzinfo) -> str:
    """DD/MM/YYYY HH:MM (24-hour) in the report time zone."""
    if value is None:
        return "\u2014"
    return value.astimezone(tz).strftime("%d/%m/%Y %H:%M")
