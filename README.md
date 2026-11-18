# EPIC — Evidence Platform Information Center

EPIC is an evidence-centered debate platform designed to keep debates on a fixed question, distinguish fact from inference and opinion, and connect each factual claim to reviewable evidence.

## Current working foundation

- FastAPI backend with interactive OpenAPI documentation
- SQLite development database, configurable for PostgreSQL
- Fixed-question debate records
- Factual, inferential, and opinion claim classification
- Automatic citation requirements for non-opinion claims
- Rule-based review flags for pivot-style phrasing. These flags do not label a claim off-topic.
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
- Automated research-job creation
- Live progress polling and progress bars
- Direct access to the evidence, challenge, argument, and ruling APIs

Run the backend and open `http://127.0.0.1:8000/` for the application or `/docs` for the complete API workspace.

The included in-process worker is appropriate for local development and demonstrations. A production deployment should replace it with a durable queue such as Celery/RQ plus Redis, use PostgreSQL, enforce authorization on every write route, and deploy behind HTTPS.

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

See `docs/PRODUCTION_DEPLOYMENT.md` for security and release requirements. Local automatic worker threads remain enabled only as a developer convenience; production mode leaves queued work for the durable worker process.


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

This creates a temporary clean database, applies every Alembic migration, and runs the complete automated test suite.

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
