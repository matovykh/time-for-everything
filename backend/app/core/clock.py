"""Single source of "now" so tests can freeze time (monkeypatch `clock.now`)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


def _system_now() -> datetime:
    return datetime.now(UTC)


class _Clock:
    def __init__(self) -> None:
        self._override: datetime | None = None

    def now(self) -> datetime:
        return self._override or _system_now()

    def set(self, value: datetime | None) -> None:
        if value is not None and value.tzinfo is None:
            raise ValueError("clock override must be timezone-aware")
        self._override = value


clock = _Clock()


def utc(dt: datetime | None) -> datetime | None:
    """Normalise DB values (SQLite returns naive datetimes) to aware UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def local_date(tz_name: str, at: datetime | None = None) -> date:
    return (at or clock.now()).astimezone(ZoneInfo(tz_name)).date()


def is_valid_timezone(name: str) -> bool:
    if not name or len(name) > 64:
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return name in _zones()


_ZONES: set[str] | None = None


def _zones() -> set[str]:
    global _ZONES
    if _ZONES is None:
        _ZONES = available_timezones()
    return _ZONES


def iso(dt: datetime | None) -> str | None:
    """RFC 3339 UTC with milliseconds and Z suffix."""
    if dt is None:
        return None
    dt = utc(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_date(d: date | None) -> str | None:
    return d.isoformat() if d else None
