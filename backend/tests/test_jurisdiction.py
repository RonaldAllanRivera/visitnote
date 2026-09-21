"""Jurisdiction derivation.

A user should not have to answer a question the system can already infer. The zone
they capture in is the strongest available signal, and onboarding already asks for it.
"""

import pytest

from app.core.jurisdiction import jurisdiction_for_timezone
from app.models.enums import Jurisdiction


@pytest.mark.parametrize(
    ("timezone", "expected"),
    [
        ("Asia/Manila", Jurisdiction.PH),
        ("America/Los_Angeles", Jurisdiction.US),
        ("America/New_York", Jurisdiction.US),
        ("UTC", Jurisdiction.US),
        ("Europe/London", Jurisdiction.US),
    ],
)
def test_jurisdiction_is_derived_from_the_capture_timezone(
    timezone: str, expected: Jurisdiction
) -> None:
    assert jurisdiction_for_timezone(timezone) is expected


def test_an_unrecognised_zone_falls_back_to_us_rather_than_raising() -> None:
    """Onboarding must never fail closed on a zone we have not mapped.

    US is the safe default: it permits both capture modes, so the fallback never
    silently grants a PH user a capability RA 4200 forbids.
    """
    assert jurisdiction_for_timezone("Mars/Olympus_Mons") is Jurisdiction.US
