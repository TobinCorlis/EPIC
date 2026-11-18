# EPIC Build Plan

## Phase 1 — Debate foundation — complete

- Fixed debate question and debate lifecycle
- Claim creation and claim-type classification
- Citation-required logic
- Initial topic-lock moderation

## Phase 2 — Evidence foundation — complete

- Source registry
- Pinpoint citations
- Claim-to-evidence relationships
- Supporting, contradicting, and contextual evidence stances
- Provisional source-quality scoring and rationale
- Relevance-weighted claim evidence summaries
- Duplicate protection and automated tests

## Phase 3 — Structured argument engine — complete

- Participants and debate sides
- Premise, conclusion, rebuttal, and concession relationships
- Argument-chain validation
- Evidence challenges and responses
- Source verification states
- Moderator rulings with an immutable audit trail

## Phase 4 — Research and knowledge bank — next

- Reusable verified sources and claims across debates
- Topic dossiers
- Contradiction and duplicate-claim detection
- Research queues and progress status

## Phase 5 — User experience

- Web application
- Invite links and guest participation
- Evidence cards and claim drill-downs
- Voice input, narration preview, and selectable narration voices
- Exportable debate reports and transcripts

## Phase 6 — Resolution and safety

- Debate timeout and non-response handling
- Factually-concluded review workflow
- Appeals and correction process
- Privacy, abuse prevention, and operational monitoring

## Completed: Research and knowledge bank

- Reusable topic dossiers
- Reusable source-to-dossier links
- Canonical knowledge claims with deterministic fingerprints
- Exact normalized duplicate prevention
- Similar-claim matching
- Contradiction candidate discovery
- Human-reviewable contradiction status
- Research jobs with queued/running/completed/failed/cancelled states
- Monotonic percentage progress
- Append-only research progress events

## Next recommended stage

Build the asynchronous research worker contract and the user-facing debate room: task queue integration, research result ingestion, authentication/authorization, live progress delivery, and a web interface for claims, evidence, challenges, and rulings.

## Completed: v0.7 real-time collaboration

- Expiring and revocable invitation links
- Optional email-bound invitations
- Account-linked debate participants
- Durable debate event history with cursor-based catch-up
- Authenticated WebSocket debate rooms
- Owner/staff invitation controls
- Collaboration migration and API tests


## Completed in v0.8
- Durable debate-room state
- Enforced participant turn order
- Configurable turn limits
- Expiration and owner-controlled skipping
- Reconnect-safe transcript retrieval
- Live browser debate-room interface
- WebSocket delivery of durable room events
