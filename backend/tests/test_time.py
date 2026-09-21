"""The UTC rule.

These are the tests the timezone design exists for. They need no database, so they
fail fast and they fail loudly.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.time import duration_seconds, ensure_utc, to_local, utcnow


def test_utcnow_is_aware_and_utc() -> None:
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_ensure_utc_rejects_naive_datetime() -> None:
    """Silently assuming a timezone is how a visit lands on the wrong calendar day."""
    with pytest.raises(ValueError, match="naive datetime rejected"):
        ensure_utc(datetime(2026, 3, 8, 12, 0))  # noqa: DTZ001 -- deliberately naive


def test_ensure_utc_converts_from_another_zone() -> None:
    la = datetime(2026, 1, 15, 22, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert ensure_utc(la) == datetime(2026, 1, 16, 6, 0, tzinfo=UTC)


def test_overnight_shift_duration_is_positive() -> None:
    """A 22:00-06:00 shift is the normal case in home care, not an edge case.

    Subtracting clock times gives -16 hours and a spurious MISSING_SHIFT_TIMES.
    Measuring absolute instants gives 8 hours.
    """
    tz = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 1, 15, 22, 0, tzinfo=tz)
    end = datetime(2026, 1, 16, 6, 0, tzinfo=tz)
    assert duration_seconds(start, end) == 8 * 3600


def test_shift_across_spring_dst_transition_is_one_hour_shorter() -> None:
    """On 8 March 2026 US clocks jump 02:00 -> 03:00.

    A shift with identical clock times to any other night is genuinely an hour
    shorter, and a caregiver paid by the hour will notice if we get it wrong.
    """
    tz = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 3, 7, 22, 0, tzinfo=tz)
    end = datetime(2026, 3, 8, 6, 0, tzinfo=tz)
    assert duration_seconds(start, end) == 7 * 3600


def test_shift_across_autumn_dst_transition_is_one_hour_longer() -> None:
    """On 1 November 2026 US clocks fall back 02:00 -> 01:00."""
    tz = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 10, 31, 22, 0, tzinfo=tz)
    end = datetime(2026, 11, 1, 6, 0, tzinfo=tz)
    assert duration_seconds(start, end) == 9 * 3600


def test_to_local_renders_in_the_visits_own_zone() -> None:
    """A note is read in the timezone it was captured in, not the reader's."""
    instant = datetime(2026, 1, 16, 6, 0, tzinfo=UTC)
    local = to_local(instant, "America/Los_Angeles")
    assert (local.hour, local.day) == (22, 15)
