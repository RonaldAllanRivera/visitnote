"""Rules both note formats share, and the transcript rendering they both receive.

**This file is part of the versioned prompt surface.** The version modules compose
`SHARED_RULES` into their system prompts, so editing it changes what every existing
prompt version means -- and every note already stored with
`prompt_version = shift_note_v1` would then be attributing itself to text that no
longer exists.

The rule is therefore the same as for the version modules themselves: do not edit
these rules in place. Add `shift_note_v2` and `soapie_v2` with the new shared text,
and promote them through the eval gate. What may be changed here freely is the
rendering below, which is mechanical and carries no instruction.
"""

from app.transcription import TranscriptTurn

# How much more the dominant speaker must talk before the inference is trusted.
# Anything below this is a two-way conversation in which either party could be the
# caregiver, and a wrong guess turns every patient quote in the note into a
# fabrication.
_DOMINANCE_RATIO = 1.5

SHARED_RULES = """\
CORE RULES

1. Never invent information. If the transcript does not support a section, set that
   section to null and raise the matching flag. Fabrication is the worst failure this
   system can produce: these notes are clinical and legal records, and in the nurse
   tier they are also a billing claim.

2. Be factual, not interpretive.
   Correct:   Patient refused lunch and stated "I'm not hungry."
   Incorrect: Patient appeared moody.

3. Quote the speaker's own words for subjective statements, and only where the
   speaker is known. A statement whose speaker cannot be determined is never placed
   in the note as a patient quote: record it as an unattributed observation and raise
   UNATTRIBUTED_STATEMENT. Guessing is forbidden.

4. Never use these phrases: "doing well", "no issues", "seemed fine", "a little off",
   "routine visit", "routine check-up", "care provided as ordered", or "stable"
   without the data supporting it. They document nothing. Replace each with the
   specific observation, or set the section to null and flag it.

5. Be specific and measurable: "ate half of lunch", "wound 2x3 cm, Stage II",
   "more confused after 8pm" -- not "ate a bit", "wound looks better", "confused".

6. Omit interpersonal complaints and venting from the note entirely, and raise the
   venting flag instead.

7. Report times exactly as stated. Never estimate, round, or infer a time that was
   not spoken.
"""


def infer_recording_speaker(
    turns: list[TranscriptTurn] | tuple[TranscriptTurn, ...],
) -> str | None:
    """Which speaker label belongs to the person who made the recording, if clear.

    The caregiver arrives, opens the conversation, and does most of the structured
    talking, so "opened and dominated" is a good signal. It is only a signal, though,
    and the cost of being wrong is asymmetric: an unknown speaker costs one
    UNATTRIBUTED_STATEMENT flag, while a wrong one puts the patient's name on words
    the caregiver said. Anything short of clear returns None.
    """
    if not turns:
        return None

    durations: dict[str, int] = {}
    for turn in turns:
        durations[turn.speaker_label] = durations.get(turn.speaker_label, 0) + (
            turn.end_ms - turn.start_ms
        )

    if len(durations) == 1:
        return next(iter(durations))

    ranked = sorted(durations.items(), key=lambda item: item[1], reverse=True)
    (leader, leader_ms), (_, runner_up_ms) = ranked[0], ranked[1]

    if leader != turns[0].speaker_label:
        return None
    if runner_up_ms == 0 or leader_ms < runner_up_ms * _DOMINANCE_RATIO:
        return None
    return leader


def render_transcript(
    turns: list[TranscriptTurn] | tuple[TranscriptTurn, ...],
    *,
    recording_speaker: str | None,
    diarized: bool,
) -> str:
    """The user content: speaker roles first, then the transcript's turns.

    Roles come first because they change how every line below them must be read.

    `diarized` must come from the template (`spec.requires_diarization`), never be
    inferred by counting distinct speaker labels in `turns`. A recording with one
    speaker label is ambiguous on its own: it is what a single-speaker dictated
    recap looks like, but it is equally what a diarized US home visit looks like
    when the patient never speaks -- and that second case must still carry the
    attribution caution below. Only the template says which one this is.
    """
    if not diarized:
        # A dictated recap has no second party for a statement to be unattributable
        # to, so the caution below does not apply -- and the flag it would ask for
        # is not even declared for this kind of template. Naming it here anyway
        # would ask the model for a code its own schema then rejects.
        roles = (
            "SPEAKER ROLES\n"
            "This is a single-speaker dictated recap: the nurse speaking aloud "
            "afterward to record the visit, not a live conversation with anyone "
            "else. Every statement in it is the nurse's own by construction."
        )
    elif recording_speaker is None:
        roles = (
            "SPEAKER ROLES\n"
            "The speaker who made this recording could not be determined. Do not guess "
            "which speaker is the patient and which is the caregiver. Any statement you "
            "would otherwise record as a patient quote must instead be written as an "
            "unattributed observation, and you must raise UNATTRIBUTED_STATEMENT."
        )
    else:
        roles = (
            "SPEAKER ROLES\n"
            f"{recording_speaker} is the caregiver or nurse who made this recording. "
            "Other speakers are the patient or a family member. Where a speaker's "
            "identity beyond that is unclear, attribute nothing and raise "
            "UNATTRIBUTED_STATEMENT."
        )

    lines = "\n".join(
        f"[{_timestamp(turn.start_ms)}] {turn.speaker_label}: {turn.text}" for turn in turns
    )
    return f"{roles}\n\nTRANSCRIPT\n{lines}\n"


def _timestamp(milliseconds: int) -> str:
    total_seconds, _ = divmod(max(milliseconds, 0), 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"
