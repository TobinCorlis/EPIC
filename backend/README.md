
## Version 0.9 — Assisted turn moderation

EPIC now analyzes live turns before publication without allowing the automated check to make a final factual ruling. The turn preview and submission workflow checks for explicit pivots/whataboutism, likely factual assertions without a URL citation, and rebuttals that fail to identify the turn being answered. Flagged turns are preserved in a durable moderation queue. Debate owners, moderators, and administrators can approve or reject each item with a written note; every action is added to the debate event history.

Key endpoints:

- `POST /debates/{debate_id}/turns/preview`
- `GET /debates/{debate_id}/moderation-reviews`
- `POST /moderation-reviews/{review_id}/decision`

The deterministic analyzer is intentionally conservative and auditable. It is an initial policy engine, not a truth detector or replacement for human review.
