
## Version 0.9 — Rule-based turn moderation

EPIC checks live turns with deterministic text rules before publication. It does not use a model, and it does not decide that a turn is off-topic. Pivot-style phrasing is flagged for a person to review. The same queue also holds likely factual assertions without a URL and rebuttals that do not identify the turn they answer. Debate owners, moderators, and administrators can approve or reject each item with a written note; every action is added to the debate event history.

Key endpoints:

- `POST /debates/{debate_id}/turns/preview`
- `GET /debates/{debate_id}/moderation-reviews`
- `POST /moderation-reviews/{review_id}/decision`

The deterministic analyzer is intentionally conservative and auditable. It is an initial policy engine, not a truth detector or replacement for human review.
