"""Per-note cost computation.

Recorded on every job so margin is visible without opening a vendor dashboard. The
arithmetic is in Decimal throughout: these are fractions of a cent multiplied by
millions of tokens, and a float here produces a number nobody trusts.
"""

from decimal import Decimal

from app.llm.costs import ModelPrice, compute_cost

PRICES = {
    "test-model": ModelPrice(
        input_usd_per_mtok=Decimal("2"), output_usd_per_mtok=Decimal("10")
    )
}


def test_a_million_input_tokens_costs_exactly_the_listed_rate() -> None:
    cost = compute_cost(
        model_id="test-model",
        input_tokens=1_000_000,
        output_tokens=0,
        audio_minutes=Decimal("0"),
        prices=PRICES,
        transcription_usd_per_minute=Decimal("0"),
    )

    assert cost == Decimal("2")


def test_input_and_output_are_priced_separately() -> None:
    """Output is five times the price of input; averaging them would misreport margin."""
    cost = compute_cost(
        model_id="test-model",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        audio_minutes=Decimal("0"),
        prices=PRICES,
        transcription_usd_per_minute=Decimal("0"),
    )

    assert cost == Decimal("12")


def test_transcription_minutes_are_included() -> None:
    """Audio is usually the larger half of a note's cost, not a rounding error."""
    cost = compute_cost(
        model_id="test-model",
        input_tokens=0,
        output_tokens=0,
        audio_minutes=Decimal("30"),
        prices=PRICES,
        transcription_usd_per_minute=Decimal("0.01"),
    )

    assert cost == Decimal("0.30")


def test_an_unpriced_model_reports_no_cost_rather_than_zero() -> None:
    """A silent zero would read as a free note and quietly overstate margin."""
    cost = compute_cost(
        model_id="some-model-nobody-priced",
        input_tokens=500_000,
        output_tokens=500_000,
        audio_minutes=Decimal("10"),
        prices=PRICES,
        transcription_usd_per_minute=Decimal("0.01"),
    )

    assert cost is None


def test_fractional_token_counts_do_not_drift() -> None:
    """The failure a float would produce: 0.006000000000000001 instead of 0.006."""
    cost = compute_cost(
        model_id="test-model",
        input_tokens=3_000,
        output_tokens=0,
        audio_minutes=Decimal("0"),
        prices=PRICES,
        transcription_usd_per_minute=Decimal("0"),
    )

    assert cost == Decimal("0.006")


def test_the_configured_defaults_price_the_default_model() -> None:
    """A deployment that never touches pricing config must still record real costs."""
    from app.core.config import get_settings

    settings = get_settings()

    assert settings.llm_model_id in settings.llm_prices
