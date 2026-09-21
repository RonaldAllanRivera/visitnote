"""Time handling.

One rule, enforced in one place: every datetime in this system is timezone-aware and
stored in UTC. Naive datetimes are a correctness bug here, not a style preference --
the most severe flag the product raises is a missing shift time, and a shift that runs
22:00 to 06:00 crosses midnight. Subtracting clock times to measure it yields a negative
duration and a spurious critical flag.

Ruff's DTZ rules reject naive construction at lint time; this module provides the
sanctioned alternatives.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    """The only sanctioned 'now' in the codebase."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalise an aware datetime to UTC, rejecting naive input.

    Raising on naive input is deliberate. Silently assuming a timezone is how a note
    ends up recording a visit on the wrong calendar day.
    """
    if value.tzinfo is None:
        raise ValueError("naive datetime rejected: all datetimes must be timezone-aware")
    return value.astimezone(UTC)


def to_local(value: datetime, timezone: str) -> datetime:
    """Render a stored UTC instant in a visit's own IANA timezone.

    Notes, PDFs, and analytics buckets are presented in the timezone the visit was
    captured in -- not the viewer's -- so a night shift reads correctly to everyone.
    """
    return ensure_utc(value).astimezone(ZoneInfo(timezone))


def duration_seconds(start: datetime, end: datetime) -> int:
    """Elapsed seconds between two instants, computed on UTC instants.

    Because both sides are absolute instants, a shift crossing midnight or a DST
    transition measures correctly without special-casing either.
    """
    return int((ensure_utc(end) - ensure_utc(start)).total_seconds())
