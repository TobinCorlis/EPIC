import hashlib
import re
from dataclasses import dataclass

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from", "has", "have", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "will", "with",
}
NEGATIONS = {"no", "not", "never", "none", "without", "cannot", "can't", "didn't", "doesn't", "isn't", "wasn't"}


@dataclass(frozen=True)
class MatchResult:
    similarity: float
    duplicate: bool
    contradiction_candidate: bool
    reason: str


def normalize_claim(text: str) -> str:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return " ".join(word for word in words if word not in STOP_WORDS)


def fingerprint_claim(text: str) -> str:
    return hashlib.sha256(normalize_claim(text).encode("utf-8")).hexdigest()


def token_set(text: str) -> set[str]:
    return set(normalize_claim(text).split())


def jaccard_similarity(left: str, right: str) -> float:
    a, b = token_set(left), token_set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def has_negation(text: str) -> bool:
    return bool(token_set(text) & NEGATIONS)


def compare_claims(left: str, right: str) -> MatchResult:
    similarity = jaccard_similarity(left, right)
    duplicate = similarity >= 0.82
    contradiction = similarity >= 0.45 and has_negation(left) != has_negation(right)
    reason = ""
    if duplicate:
        reason = "Claims share substantially the same normalized language."
    elif contradiction:
        reason = "Claims discuss substantially overlapping terms but differ in explicit negation."
    return MatchResult(round(similarity, 4), duplicate, contradiction, reason)
