"""Deriving a jurisdiction from the zone a user captures in.

Kept as a pure function with no session and no settings, so onboarding, the seed CLI,
and the eval fixtures all reach the same answer for the same input.
"""

from app.models.enums import Jurisdiction

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
