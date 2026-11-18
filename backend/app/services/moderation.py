import re
from dataclasses import dataclass


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
    note: str | None = None


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9']+", text.lower())
        if len(token) > 3
    }


def evaluate_topic_alignment(fixed_question: str, submission: str) -> ModerationResult:
    normalized = submission.lower()
    if any(marker in normalized for marker in PIVOT_MARKERS):
        return ModerationResult(False, "Possible pivot or whataboutism detected.")

    question_terms = _terms(fixed_question)
    submission_terms = _terms(submission)
    overlap = question_terms.intersection(submission_terms)

    if question_terms and not overlap:
        return ModerationResult(False, "The submission does not appear responsive to the fixed debate question.")

    return ModerationResult(True)
