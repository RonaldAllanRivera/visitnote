"""Deriving a jurisdiction from the zone a user captures in.

Kept as a pure function with no session and no settings, so onboarding, the seed CLI,
and the eval fixtures all reach the same answer for the same input.
"""

from typing import NamedTuple

from app.models.enums import CaptureMode, Jurisdiction

# Explicit rather than a prefix match on "Asia/". The product operates in exactly two
# jurisdictions, and a nurse in Asia/Singapore is not a Philippine nurse.
_PH_ZONES: frozenset[str] = frozenset({"Asia/Manila"})


def jurisdiction_for_timezone(timezone: str) -> Jurisdiction:
    """The jurisdiction implied by an IANA zone, defaulting to US.

    US is the fallback because it is the permissive regime: it allows both capture
    modes. Defaulting an unmapped zone to PH would silently restrict a user; defaulting
    to US never grants a PH user a capability RA 4200 forbids, because PH is only ever
    reached by an explicit match or an explicit choice.
    """
    return Jurisdiction.PH if timezone in _PH_ZONES else Jurisdiction.US


class CaptureRestriction(NamedTuple):
    """A capture mode a jurisdiction does not permit, and the statute behind it."""

    code: str
    mode: CaptureMode
    message: str


# Jurisdictions in which recording a third party is not lawfully obtainable, and the
# statute that says so. Data rather than a branch, so adding a jurisdiction is a row.
#
# It lives here, beside `jurisdiction_for_timezone`, because two callers now need it:
# the service that refuses the visit, and the profile that tells a client not to offer
# the mode in the first place. A second copy in either place would be a second version
# of a criminal-law constraint.
CAPTURE_RESTRICTIONS: dict[Jurisdiction, CaptureRestriction] = {
    Jurisdiction.PH: CaptureRestriction(
        code="RA_4200",
        mode=CaptureMode.LIVE_AUDIO,
        message=(
            "RA 4200 (Anti-Wiretapping Act) requires the consent of all parties to a "
            "private communication. Record a spoken recap instead."
        ),
    ),
}


def capture_restriction_for(jurisdiction: Jurisdiction) -> CaptureRestriction | None:
    """The restriction this jurisdiction imposes on capture, if any."""
    return CAPTURE_RESTRICTIONS.get(jurisdiction)


def allowed_capture_modes(jurisdiction: Jurisdiction) -> list[CaptureMode]:
    """Every capture mode this jurisdiction permits.

    Derived by subtraction from the full set rather than listed per jurisdiction: a
    new capture mode is then permitted everywhere it is not explicitly restricted,
    which is the correct default for a mode nobody has written a statute about.
    """
    restriction = CAPTURE_RESTRICTIONS.get(jurisdiction)
    return [mode for mode in CaptureMode if restriction is None or mode is not restriction.mode]
