"""Deepgram transcription provider.

The only module in the system that knows Deepgram exists. Everything downstream sees
`Transcription` and `TranscriptTurn`.

The model identifier is not written here. It comes from configuration, because model
lineups move faster than source code does and a model change must be a configuration
change rather than a deployment.
"""

import logging
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.transcription.base import (
    Transcription,
    TranscriptTurn,
    raw_text_from,
    speaker_count_of,
)

logger = logging.getLogger(__name__)

API_URL = "https://api.deepgram.com/v1/listen"

# Long, because this is a whole visit recording being transcribed in one request and
# the failure mode of a short timeout is a retry that costs money and still times out.
REQUEST_TIMEOUT_SECONDS = 600.0


class DiarizationUnavailableError(Exception):
    """A diarize=True request came back with no speaker turns.

    Treated as a failure rather than degraded to a flat transcript. An undiarized
    transcript makes every patient quote unverifiable, and the note prompts are
    required to quote the patient -- so the pipeline would produce exactly the
    fabrication this provider exists to prevent. Only raised when diarization was
    requested: under diarize=False a response with no utterances is not a failure,
    it is one speaker producing nothing Deepgram chose to segment.
    """


def parse_response(payload: dict[str, Any], *, model_id: str, diarize: bool) -> Transcription:
    """Turn a /v1/listen response into the protocol's own types.

    `diarize` gates the "no utterances" check, not just the request param sent
    earlier: a PH spoken recap genuinely has one speaker, so a diarize=False call
    coming back with a single implied speaker_0 turn is the expected, correct
    result, not diarization failing to run.
    """
    results = payload.get("results", {})
    utterances = results.get("utterances")
    if diarize and not utterances:
        raise DiarizationUnavailableError(
            "response contained no utterances; diarization did not run"
        )

    turns = tuple(
        TranscriptTurn(
            speaker_label=f"speaker_{utterance.get('speaker', 0)}",
            start_ms=round(float(utterance["start"]) * 1000),
            end_ms=round(float(utterance["end"]) * 1000),
            text=str(utterance.get("transcript", "")).strip(),
        )
        for utterance in (utterances or [])
    )

    return Transcription(
        turns=turns,
        # Rebuilt from the turns rather than copied from the channel transcript, so
        # the text the fabrication checker searches is exactly the text the model was
        # shown. Two near-identical strings that can diverge is a bug waiting to
        # happen.
        raw_text=raw_text_from(turns),
        speaker_count=speaker_count_of(turns),
        confidence=_confidence(results, utterances),
        provider="deepgram",
        model_id=model_id,
    )


def _confidence(results: dict[str, Any], utterances: list[dict[str, Any]]) -> float:
    """Whole-transcript confidence, recorded so a bad recording is visible later.

    Prefers the channel alternative's figure, which is computed over the entire
    audio; the mean of per-utterance scores is the fallback when only those exist.
    """
    channels = results.get("channels") or []
    if channels:
        alternatives = channels[0].get("alternatives") or []
        if alternatives and "confidence" in alternatives[0]:
            return float(alternatives[0]["confidence"])

    scores = [float(u["confidence"]) for u in utterances if "confidence" in u]
    return sum(scores) / len(scores) if scores else 0.0


class DeepgramProvider:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.deepgram_api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set")
        self._api_key = settings.deepgram_api_key
        self._model_id = settings.transcription_model_id
        self._redact_pii = settings.deepgram_redact_pii

    async def transcribe(self, audio: Path, *, diarize: bool) -> Transcription:
        params: dict[str, str] = {
            "model": self._model_id,
            # Per-call, not hardcoded: a US template requires it, a PH template does
            # not, and the caller states which via the required `diarize` keyword.
            "diarize": "true" if diarize else "false",
            # Gives back utterance-level turns instead of per-word speaker tags,
            # which would leave this module doing the segmentation itself. Requested
            # regardless of diarize, so a diarize=False call still gets segmented
            # turns rather than one undifferentiated blob.
            "utterances": "true",
            "punctuate": "true",
            "smart_format": "true",
        }
        if self._redact_pii:
            # An additional layer before text reaches the LLM, not a substitute for
            # the pseudonymous label: a recording is inherently identifying.
            params["redact"] = "pii"

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                API_URL,
                params=params,
                headers={
                    "Authorization": f"Token {self._api_key}",
                    "Content-Type": "audio/wav",
                },
                content=audio.read_bytes(),
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()

        return parse_response(payload, model_id=self._model_id, diarize=diarize)
