"""Eval clock in Europe/Warsaw. Live scholarship amounts keep date.today()."""
from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo("Europe/Warsaw")


def timezone_name() -> str:
    raw = (os.getenv("UNIVERSITY_TIMEZONE") or "").strip()
    return raw or "Europe/Warsaw"


def zone() -> ZoneInfo:
    name = timezone_name()
    if name != "Europe/Warsaw":
        # Phase 0 does not invent another campus zone. Unknown stays Warsaw
        # only when the env matches the known IANA name; anything else is refused.
        raise ValueError(f"unsupported UNIVERSITY_TIMEZONE: {name}")
    return WARSAW


def as_of_datetime(value: str) -> datetime:
    """Parse an eval as_of. A bare date is that civil day at 12:00 in Warsaw.

    Noon avoids the DST spring-forward gap (02:00 local does not exist).
    """
    text = (value or "").strip()
    if not text:
        raise ValueError("as_of is empty")
    if len(text) == 10:
        day = date.fromisoformat(text)
        return datetime(day.year, day.month, day.day, 12, 0, tzinfo=zone())
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=zone())
    return parsed.astimezone(zone())


def today(as_of: str | None = None) -> date:
    if as_of:
        return as_of_datetime(as_of).date()
    return datetime.now(zone()).date()


def academic_year(as_of: str | None = None) -> str:
    """Same October boundary as facts.current_academic_year, on a Warsaw date.

    Pass as_of from an eval case. The live helper is unchanged and still
    defaults to date.today() on the server clock.
    """
    day = today(as_of)
    if day.month >= 10:
        return f"{day.year}/{day.year + 1}"
    return f"{day.year - 1}/{day.year}"


def offset_hours(as_of: str) -> int:
    moment = as_of_datetime(as_of)
    offset = moment.utcoffset()
    if offset is None:
        raise RuntimeError("Warsaw clock returned a naive datetime")
    return int(offset.total_seconds() // 3600)
