import re
from dataclasses import dataclass


# Phrases that can indicate a change of subject. They are a review flag only.
# Matching one is not a finding of whataboutism or of being off-topic.
PIVOT_MARKERS = {
    "what about",
    "but they also",
    "instead let's talk about",
    "the real issue is",
    "regardless of the question",
}


@dataclass(frozen=True)
class ModerationResult:
    on_topic: bool
    needs_review: bool = False
    note: str | None = None


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9']+", text.lower())
        if len(token) > 3
    }


def evaluate_topic_alignment(fixed_question: str, submission: str) -> ModerationResult:
    """Flag phrasing for a person to review. Do not label the text off-topic.

    Shared words and pivot-style phrases are weak signals. They are not a
    finding that a submission is irrelevant.
    """
    normalized = submission.lower()
    if any(marker in normalized for marker in PIVOT_MARKERS):
        return ModerationResult(
            on_topic=True,
            needs_review=True,
            note=(
                "Flagged for review. Pivot-style phrasing is present. "
                "This is not a finding that the submission is off-topic."
            ),
        )

    question_terms = _terms(fixed_question)
    submission_terms = _terms(submission)
    # Short submissions often omit the question's vocabulary. Do not flag those
    # on word overlap alone; a person can still review them.
    if question_terms and not question_terms.intersection(submission_terms) and len(submission.split()) >= 18:
        return ModerationResult(
            on_topic=True,
            needs_review=True,
            note=(
                "Flagged for review. The submission does not share longer words with the fixed question. "
                "This is not a finding that the submission is off-topic."
            ),
        )

    return ModerationResult(on_topic=True, needs_review=False)
