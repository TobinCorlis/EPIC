# EPIC — Evidence Platform Information Center

EPIC is an evidence-centered debate platform designed to keep debates on a fixed question, distinguish fact from inference and opinion, and connect each factual claim to reviewable evidence.

## What this build does and does not do

Implemented:

- Debate, claim, source, citation, and evidence-link records. A source needs a URL or a document reference. Each evidence link states the claim it supports.
- `verified` and `archived` only through a logged-in verification event with a method and an archive URL or snapshot hash. New claims and sources start unverified.
- Evidence listed by item. Declared source type stays unverified until a moderator reviews it. Ranking uses evidence tier and source independence. Scores are not added together.
- Uncertainty on claims, and a correction log (original text, replacement, reason, time, author) included in reads and debate exports.
- Rule-based review flags. Phrases such as "what about" are not labelled off-topic.
- Accounts, PBKDF2 passwords, bearer sessions whose lifetime follows `SESSION_HOURS`, and logout that deletes the server session. `SECRET_KEY` is the HMAC key for session token hashes.
- Optional authorization. With `ENFORCE_AUTHORIZATION=true`, knowledge writes, argument creation, and evidence challenges require a logged-in user with the permissions described below. `python -m app.cli create-admin` creates the first administrator.
- A research-job queue. The worker records that automated research is not implemented. It does not search, compare claims, or mark a job completed.

Not implemented:

- Automated source search, claim comparison, or a completed research result.
- An AI or model that judges relevance, truth, or rulings. The "AI assistant" value is a participant role label.
- Treating a self-declared source type, publisher, or author string as reviewed evidence.
- A summed evidence score.

`ALLOWED_ORIGINS` and `TRUSTED_HOSTS` accept a comma-separated list, as in `.env.example`, or a JSON list.

## Current working foundation

- FastAPI backend with interactive OpenAPI documentation
- SQLite development database, configurable for PostgreSQL
- Fixed-question debate records
- Factual, inferential, and opinion claim classification
- Automatic citation requirements for non-opinion claims
- Rule-based review flags for pivot-style phrasing. These flags do not label a claim off-topic.
- Rule-based scope flags. They compare the population, timeframe, geography, metric, and study type a user entered on the source, the evidence link, the claim, and the debate question. A flag means needs review. It does not reject the claim or label it off-topic. An outlier is flagged only when EPIC already has a recorded contradicting link on that claim.
- Source, citation, and claim-evidence data models
- Evidence stances: supports, contradicts, and contextualizes
- Provisional source-quality scoring with written rationale
- Relevance-weighted evidence summaries for each claim
- Duplicate-source and duplicate-link safeguards
- Participants with affirmative, negative, or neutral positions
- Structured premises, conclusions, rebuttals, and concessions
- Parent-child argument chains linked to factual claims
- Verification states for argument nodes
- Evidence challenges, responses, remedies, and resolution states
- Moderator-only rulings with rationale and rule references
- Auditable ruling history and cross-debate integrity safeguards
- Automated unit and API workflow tests

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` to use the API interactively.

## Run tests

```bash
cd backend
pytest -q
```

## Evidence workflow

1. Create a debate with a permanently fixed question.
2. Add a claim to the debate.
3. Register a source by URL or by a document reference. New sources are unverified. Archive URL and archived time are set only by a verification event.
4. Create a pinpoint citation containing a locator and optional excerpt.
5. Link that citation to a claim as supporting, contradicting, or contextual, and record the precise claim the evidence supports.
6. Request the claim's evidence summary.

Evidence is listed item by item. A self-declared source type stays unverified, and is ranked as unknown, until a moderator or administrator reviews it. Reviewed items are ordered by evidence tier. Items from the same publisher, host, or document count as one independent source. EPIC does not add item scores together, and publisher or author text does not add points.

Claim confidence is a 0–1 score with a label. It is not a verification. Automated checks record whether a cited source was found, whether a quote appears in the accessible text, and which related works a reviewer might read. A failed check is `check_failed`, not a verification and not a missing record. A source the lookups do not find is `not_findable` and scores 0 / Unsupported when the claim rests only on it. Candidate corroboration and counterevidence do not change the label. A person still records tier review, and `verified` is still a separate human event.

The rules, in order, are:

- No supporting evidence, or a cited source with no findable record, scores 0 and is labeled Unsupported. The missing citation is stored as `cited source: no record found`. A passing automated existence check — the identifier resolved, the entered metadata matches, and the work is not retracted — satisfies that record-found gate. Its provenance is `automated check`. A fetched URL with HTTP 200 counts as found for that URL. A weak OpenAlex title match does not override it, and OpenAlex title search runs only when the source has no DOI, PMID, or URL.
- A claim contradicted by stronger, independent, reviewed evidence scores 0 and is labeled Refuted. The contradicting sources are listed. A weaker or non-independent source does not force that label.
- Supported requires a score of at least 0.6 (`SUPPORT_SCORE_THRESHOLD`) and the evidence gate. A score above 0 and below that threshold is Weakly supported. The score is shown next to the label. A low score never carries Supported.
- A quote found in a source verifies attribution: the source contains that text. It does not establish that a substantive claim is true. An attribution claim ("source S says X") can reach Supported from that quote in one found, non-retracted source when the score is at least 0.6. A substantive claim ("X") cannot reach Supported from one source alone. One source quoting itself is not independent corroboration.
- A found source whose quoted text is not in the accessible text stays below Supported and is flagged. It is not labeled Unsupported. `verified` still requires a moderator and a recorded verification event, with the method and the archive URL or snapshot that was checked. Automated checks count as real checks for scoring. They do not by themselves mark a source verified.
- A retraction sets that source's track factor to 0 and records an upstream invalidation. The worker records the actor as `system:factcheck`. A moderator can reverse that invalidation with a reason. The reversal does not restore verified.
- `Unknown – not yet rated` is used when the record was found and the tier has not been reviewed, and support has not been established by a matching quote. It is not used for a missing or fabricated citation.
- Otherwise the stored formula is `tier_factor * track_factor * corroboration_factor * counter_factor`. Factors are rounded to two decimals.

- `tier_factor` is the strongest supporting source's reviewed tier rank divided by 8. An unreviewed declared type contributes as unknown, not as the declared tier. Tiers are not summed.
- `track_factor` counts only events about the source: a publisher correction or erratum, a retraction, or a claim from that source found false by an upheld challenge. A correction to the wording of an EPIC claim is not one of those events. When none of them is recorded, the factor is unknown and is left out of the product. It is not a multiplier of zero. A recorded retraction that has not been reversed makes the factor 0.
- `corroboration_factor` is the number of independent supporting sources, capped at 3, divided by 3.
- `counter_factor` is 1 divided by 1 plus the number of independent contradicting sources whose challenge was not upheld. Upheld challenges refute that contrary evidence and it is reported, then excluded. Nothing outside the database is invented.

Scope checks use only the population, timeframe, geography, metric, and study type a user entered, plus a few wording patterns (some stated as all, a correlation or observational study stated as causation, a city or state study stated as national). They do not read an external paper. A flag means needs review. It does not reject the claim. An outlier is flagged only when a contradicting link is already recorded on that claim. A near match on question text with a different entered scope is a different question.

## Scoring standards

Credibility is judged only on checkable evidence for the claim: whether the data or method can be verified, whether the cited study or test exists and was done, the source's record of corrections and false information, and independent corroboration. EPIC does not down-weight a source because of who published it or which group they belong to, and it does not censor. Scoring is per claim. A correct sub-claim keeps its support when a different conclusion from the same source is Refuted. Nothing is Refuted without recorded counterevidence on that claim.

A question marked not factually answerable — fiction, pure opinion, or a hypothetical such as which fictional crew would win — has no confidence score and no Supported or Refuted label. The page says the question has no factual answer. A factual sub-claim can still be scored. That question is not stored in or reused from the factual reference library.

## Automated fact checking

Checks run when a source is added or edited, when a citation or evidence link is added, on demand from `POST /sources/{id}/checks` or `POST /claims/{id}/checks`, and on a periodic re-check. The worker is `python -m app.services.factcheck_worker`. Every check is an immutable row: checker name and version, API, query, response id, and timestamp.

What is checked:

- A DOI is looked up at Crossref. Title, authors, year, and journal are compared with the fields that were entered. A mismatch is flagged. The work is still recorded as found.
- A PMID is looked up in PubMed. The same metadata comparison applies. Retraction, erratum, and expression-of-concern publication types are recorded.
- OpenAlex title search runs only when the source has no DOI, no PMID, and no URL. A match score under 0.72 is `low_confidence` and does not override a URL that returned HTTP 200.
- Crossref `update-to` on a record means that record updates or retracts the target DOI. `updated-by`, and a relation such as `retraction` whose target is another DOI, means this record is the one that was retracted or corrected. A retraction notice is recorded as `retraction_notice` and does not start the cascade or zero the track record. A retraction of this record starts the upstream invalidation cascade and updates the source track record. The same cascade is not run twice for one source. An auto-created notice source uses the Crossref title.
- A URL is fetched. The row stores HTTP status, final URL, content type, retrieval time, and a content hash. The Internet Archive availability API is queried. `archived` is recorded only when a snapshot URL and timestamp come back, and only then are `archive_url` and `archived_at` set. Save Page Now runs only when `FACTCHECK_SAVE_PAGE_NOW` is true, and only a successful capture is stored.
- Federal Register, govinfo, and CourtListener adapters run when their identifier is present. govinfo uses `GOVINFO_API_KEY` when set. CourtListener uses `COURTLISTENER_API_TOKEN` when set. A 401 or 403 is `check_failed`, not a missing record.
- A citation excerpt is compared with fetched HTML, or with PDF text from pypdf or `pdftotext`. Results are found, not found in the accessible text, or text not accessible. Not found lowers the rated score by half and flags review. It does not label the claim Refuted. Inaccessible text is not treated as absence.
- OpenAlex and PubMed are searched for related work. A lead is stored only when its title overlaps the claim above `FACTCHECK_LEAD_MIN_OVERLAP` (default 0.25). OpenAlex relevance cannot rescue an off-topic title. At most `FACTCHECK_LEAD_LIMIT` leads are kept, labeled by topic-match strength. Anything below the threshold is not stored as a lead; the raw response stays in the HTTP cache. A stored lead is still not linked evidence and does not change the score.
- If `FACTCHECK_LLM_BASE_URL`, `FACTCHECK_LLM_API_KEY`, and `FACTCHECK_LLM_MODEL` are set, a model may rate the claim against the fetched text only. The rating is kept only when its quote is an exact span of that text. Otherwise the rating is discarded. The deterministic checks still run with no model configured.

What is not checked, and what a check does not do:

- A check never sets `verified`. Marking a source verified requires a recorded existence check that found the work and no retraction. Marking a claim or argument verified is blocked when a supporting source's latest check is not findable, failed, low confidence, or a retraction. If no automated check has been stored yet, the existing human evidence rules still apply, and the panel says the check has not been recorded.
- A network failure, timeout, or 5xx is `check_failed`. It is not verified and it is not not-findable.
- Candidate papers are not counterevidence in the score. Only a reviewed, linked contradicting source can refute a claim.
- Paywalled, scanned, or otherwise unreadable text is not treated as a quote that is absent.
- The research-job worker still records `not_implemented`. It does not search the literature or finish a research question.
- An AI matchup run in EPIC FABLE is still not implemented.
- EPIC does not invent a citation, an archive snapshot, or a passage that was not returned.

## EPIC FABLE

EPIC FABLE (Fictional Analysis Based on Lore Evidence) is walled off from the factual record. Lore is not evidence and does not appear in factual search or reuse. A matchup is either an AI matchup or a personal-knowledge debate. An AI matchup run is not implemented. In a debate, the debaters supply each power or feat and its canon citation. The referee rules only those moves as Allowed, Disallowed, or Unverified, and does not coach, suggest powers, answer questions, or introduce a counter the debater did not raise. A moderator can accept, override, or re-check a ruling. Debate outcomes and AI matchup outcomes are stored separately and do not overwrite each other. A side that never raises a valid canon counter can lose. EPIC cannot fully prevent a debater from consulting material outside the room.

## Reference library

The library reuses a recorded answer when a debate is opened or a claim or argument is added. A match requires the question text and the same entered scope. The answer keeps facts, interpretation, and uncertainty separate, and it links the claims, sources, and verification events already stored. EPIC does not seed answers.

A point the entry already covers is linked to that version. A point it does not cover is marked "new point, not yet researched" and queued on the research-job path. That path still records `not_implemented`. Resolving the point appends a version and a change log. The previous version stays.

Any signed-in user can request re-evaluation of an entry or a verified claim, with a reason and optional new evidence. The entry shows "re-evaluation pending" while the request is open. The decision weighs the confidence factors above. The most reliable evidence wins. The most recent evidence wins only when reliability is equal. The decision records which source won and why. Outcomes are upheld, revised, or overturned, and each one appends a version.

An upstream invalidation records that a source or verification rested on false information, fabrication, misconduct, retraction, or error, in EPIC or upstream. The invalidation has its own source. Affected claims are demoted, confidence is recomputed, dependent library entries and debates are marked stale, correction-log rows are written, and the source track record counts the invalidation. The original verification is tagged `invalidated: ...` and is not described as a legitimate past verification. A stale entry is not served as the current answer.

## Structured argument workflow

1. Add participants to a debate and assign roles and sides.
2. Create premises, conclusions, rebuttals, or concessions.
3. Link argument nodes to claims and to parent argument nodes.
4. New argument nodes start unverified. `verified` and `archived` are not set by the client or by a ruling. They are recorded only through `POST /verification-events`, which stores who, when, method, and an archive URL or snapshot hash.
5. Challenge a specific claim-evidence relationship with a stated reason and requested remedy.
6. Allow a moderator or designated AI assistant to issue a reasoned ruling.
7. Retrieve the debate's ruling history as an audit trail.
8. Record an uncertainty or gap on a claim. A correction keeps the original text, the replacement, the reason, the time, and the author. Claim reads and debate exports include that log.


## Research and knowledge bank (v0.3)

EPIC now includes reusable topic dossiers and a visible research workflow.

Key API routes:

- `POST /knowledge/dossiers` — create a reusable topic dossier
- `POST /knowledge/dossiers/{id}/sources` — attach an existing source to a dossier
- `POST /knowledge/dossiers/{id}/claims` — add a canonical knowledge claim
- `POST /knowledge/dossiers/{id}/match-claim` — find duplicate or contradiction candidates
- `GET /knowledge/dossiers/{id}/contradictions` — inspect contradiction candidates
- `PATCH /knowledge/contradictions/{id}` — review, confirm, or dismiss a candidate
- `POST /knowledge/jobs` — create a visible research job
- `PATCH /knowledge/jobs/{id}` — a moderator or administrator may cancel a job. The route rejects completion, progress, and result summaries.
- `GET /knowledge/jobs/{id}/events` — retrieve the recorded status history

Automated research is not implemented. The worker does not search sources or compare claims. It records `not_implemented` and does not mark the job completed.

The matching service uses transparent normalized-token similarity and explicit-negation detection. It only flags candidates; it does not silently merge claims or declare a contradiction resolved.

## User-facing application (v0.4)

EPIC now serves a responsive browser workspace at `/` with:

- Local account registration and login
- Secure salted PBKDF2 password storage
- Expiring bearer sessions and logout invalidation
- Authenticated workspace summary
- Debate creation and debate-room listing
- Research-job creation that records automated research as not implemented
- Live status polling and progress bars
- Direct access to the evidence, challenge, argument, and ruling APIs

Run the backend and open `http://127.0.0.1:8000/` for the application or `/docs` for the complete API workspace.

The in-process worker does not perform research. It records `not_implemented`. A production deployment should use PostgreSQL, enforce authorization, and deploy behind HTTPS. A separate queue will not create research results until a real research step exists.

## Production-hardening stage (v0.5)

EPIC now includes PostgreSQL support, a database-backed research queue, a separately runnable worker, production configuration validation, CORS/trusted-host controls, liveness/readiness checks, a non-root container image, and Docker Compose orchestration.

### Run with PostgreSQL and a worker

```bash
docker compose up --build
```

### Run the worker directly

From `backend/`:

```bash
python -m app.services.research_worker
```

See `docs/PRODUCTION_DEPLOYMENT.md` for security and release requirements. Local threads and the separate worker process both record that automated research is not implemented. Neither one marks that work completed.


## Version 0.6: migrations and authorization

Production deployments now use Alembic migrations and can enforce authenticated writes with `ENFORCE_AUTHORIZATION=true`. Debates record an owning user, account roles are `member`, `moderator`, and `administrator`, and protected debate-management operations allow only the owner or authorized platform staff.

With enforcement on, knowledge writes, argument creation, and evidence-challenge creation also require a logged-in user. Argument and challenge creation is limited to the debate owner, platform staff, or the participant linked to that user. Resolving a challenge, and confirming or dismissing a contradiction, is limited to the debate owner or staff (contradiction review: moderator or administrator).

Create the first administrator from `backend/` after the schema exists:

```bash
python -m app.cli create-admin --email admin@example.com --name "EPIC Admin" --password "replace-this-password"
```

The command refuses to run once any administrator account exists.

Run migrations from `backend/` with:

```bash
alembic upgrade head
```

## v0.8 — Real-time collaboration

EPIC now supports account-bound debate invitations and live debate-room connections.

### Collaboration endpoints

- `POST /debates/{debate_id}/invitations` — create an expiring, hashed invitation token.
- `GET /debates/{debate_id}/invitations` — review invitation status and usage.
- `DELETE /invitations/{invitation_id}` — revoke an invitation.
- `POST /invitations/accept` — join a debate using an authenticated account.
- `GET /debates/{debate_id}/events?after_id=...` — retrieve the durable room event stream.
- `WS /ws/debates/{debate_id}?token=...` — authenticated live-room WebSocket.

Invitation tokens are shown only when created; EPIC stores only their SHA-256 digest. Invitations may be bound to an email address, limited by expiration and use count, and revoked by the debate owner or platform staff. Accepted participants are linked to their user account so authorization can distinguish invited collaborators from untrusted visitors.

The database event log is the durable source for catch-up after reconnecting. WebSockets provide low-latency room presence and event delivery while connected.


## v0.8 live debate rooms

EPIC now includes durable, turn-based live debate rooms. Debate owners can configure a turn timer and first speaker. Authenticated debaters can post only during their assigned turn; room state and submitted turns persist through reconnects. Owners and platform staff can skip a stalled turn. WebSocket clients receive durable room-event updates, and the browser workspace includes a live-room view.

Key endpoints:

- `PUT /debates/{id}/room` configure or start a room
- `GET /debates/{id}/room` retrieve reconnect-safe state
- `GET /debates/{id}/turns` retrieve the turn transcript
- `POST /debates/{id}/turns` submit the active debater's turn
- `POST /debates/{id}/turns/skip` advance a stalled turn
- `WS /ws/debates/{id}` receive durable room events

# EPIC 1.0 Release Candidate 1

This package is the first consolidated build intended for direct local use.

## Fastest start on Windows

1. Install Python 3.11 or newer.
2. Extract the ZIP file.
3. Double-click `scripts\start_epic_windows.bat`.
4. Your browser opens to `http://127.0.0.1:8000`.
5. Register an account and create your first debate.

The first launch creates a private local SQLite database at `backend\epic.db`. Later launches reuse the same database, so your local work remains available unless that file is deleted.

## Fastest start on macOS or Linux

```bash
./scripts/start_epic.sh
```

Then open `http://127.0.0.1:8000`.

## Docker start

For a PostgreSQL-backed local deployment with a separate research worker:

```bash
docker compose up --build
```

Then open `http://localhost:8000`.

## Release verification

From an activated environment with dependencies installed:

```bash
python scripts/verify_release.py
```

This creates a temporary clean database, applies every Alembic migration, and runs the complete automated test suite. It then builds an unmodified v1.0-rc2 database, seeds it, upgrades that database to the current revision, and downgrades it again. Set `EPIC_UPGRADE_POSTGRES_URL` to a disposable PostgreSQL database to run the same upgrade check there. The URL's schema is dropped.

## Important deployment boundary

The one-click scripts are for private local testing. Before exposing EPIC publicly, replace development secrets, enforce authorization, use HTTPS, configure backups, and follow `docs/PRODUCTION_DEPLOYMENT.md`.

## RC2 usability additions

EPIC v1.0 RC2 adds a first-user workflow directly in the browser:

- Guided onboarding path
- Debate workspaces with tabs
- Claim creation and topic-alignment feedback
- One-step source, citation, and evidence attachment
- Evidence summary metrics per claim
- Moderator review queue with approve/reject controls
- JSON and Markdown debate exports
- Authenticated evidence writes

The Windows and macOS/Linux launch instructions remain unchanged from RC1.
