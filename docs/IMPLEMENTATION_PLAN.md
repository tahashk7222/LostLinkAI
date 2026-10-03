# LostLink AI — Implementation Plan

_Last updated: 2026-10-03_

## Status

| Phase | Status |
|---|---|
| 0 Inspection & plan | ✅ Done |
| 1 Foundation (backend, DB, auth, frontend shell) | ✅ Done |
| 2 Reporting (CRUD, private image upload, browse, details) | ✅ Done |
| 3 AI (understanding, embeddings, retrieval, matching, explanations) | ✅ Done (local providers) |
| 4 Verification, notifications, state machines, messaging | ✅ Done |
| 5 Admin (moderation, flags, cases, audit, health) | ✅ Done |
| 6–7 Integration & tests | ✅ 31 pytest tests passing; live HTTP smoke test of full demo passed; `next build` clean |
| 8 Deployment | 🟡 Dockerfiles + compose written but **not yet run** (no Docker on dev machine); Alembic migrations in place |
| UX: upload + UET location | ✅ Custom photo dropzone; UET Lahore geofence (OSM campus polygon + 500 m nearby zone), backend-enforced |

Open follow-ups: rate limiting, httpOnly-cookie auth, email delivery, pgvector-backed retrieval, frontend
automated tests, learned vision/text providers from the AI and vision teams, verified pins for unmapped UET
places (Main Library, Library Courtyard, Cafeteria, Main Gate).

## 1. Environment findings (Phase 0 inspection)

| Item | Finding | Consequence |
|---|---|---|
| Repository | `github.com/tahashk7222/LostLinkAI` exists but is **empty** (no commits) | Start fresh; push `main` + `develop` |
| OS | Windows 11 Pro, PowerShell 5.1 | Scripts provided for PowerShell; Docker files for deployment |
| Git / Node / Python | Not installed initially → installed via winget (Git, Node LTS, Python 3.12) | |
| Docker / WSL | Not installed (VirtualBox in use) | No local containers; Docker Compose provided for deployment only |
| PostgreSQL / pgvector | Not installed | Local dev uses **SQLite**; production uses **PostgreSQL** via `DATABASE_URL` |
| Env vars / API keys | None | All config via `.env`, `.env.example` committed |
| External AI | **Team decision: no external AI for now** | Local, deterministic AI modules behind provider interfaces |

## 2. Architecture

```
LostLinkAI/
├── backend/                 FastAPI (Python 3.12)
│   ├── app/
│   │   ├── main.py          app factory, routers, error handlers
│   │   ├── core/            config, security (JWT, hashing), errors, logging
│   │   ├── db/              SQLAlchemy engine/session, base
│   │   ├── models/          ORM entities
│   │   ├── schemas/         Pydantic request/response models
│   │   ├── api/routes/      auth, reports, matches, verification, cases,
│   │   │                    notifications, messages, admin, images
│   │   ├── services/        business logic (reports, storage, cases, audit…)
│   │   └── ai/              agentic pipeline (see §3)
│   │       ├── orchestrator.py
│   │       ├── understanding/   item understanding agent
│   │       ├── retrieval/       candidate retrieval
│   │       ├── matching/        scorer + explanation
│   │       ├── verification/    question generation + answer evaluation
│   │       ├── providers/       pluggable text/image embedding providers
│   │       └── config.py        configurable weights & thresholds
│   └── tests/               pytest (unit + integration + E2E scenario)
├── frontend/                Next.js (App Router) + TypeScript + Tailwind
└── docs/                    plan, architecture decisions, API notes
```

### Data flow
1. User creates report → stored immediately (never lost on AI failure).
2. Orchestrator runs: **Understanding → Retrieval → Matching → Notification**.
3. Match ≥ threshold → `MatchCandidate` (POTENTIAL_MATCH) + owner notification.
4. Owner opens match → requests verification → questions generated from the
   finder's **private** details (never shown to the owner).
5. Owner answers → system computes an **advisory** score → **finder (human)
   confirms or rejects**. AI never grants access by itself.
6. Verified → `Case` CONNECTED → in-app messaging (no emails/phones exposed).
7. Either party marks RECOVERED → case closed; both reports set RECOVERED.

## 3. AI modules (local, no external API)

All modules sit behind interfaces so Taha's reasoning layer or the vision team's
models (e.g., CLIP, OpenAI) can be plugged in by changing config.

| Agent | MVP implementation | Swap-in point |
|---|---|---|
| Orchestrator | Plain Python workflow with state, error capture, retry endpoint | — |
| Item Understanding | Rule-based extraction: category taxonomy + synonyms, colour lexicon, brand list, feature phrases. Each attribute stored with `source` = USER or AI and a confidence | `ItemUnderstandingProvider` |
| Retrieval | Structured filter (opposite type, ACTIVE, category compatibility, time window, region radius) + ranking by text-vector similarity | `CandidateRetriever` (pgvector later) |
| Text similarity | Hashed word + character n-gram TF vectors, cosine similarity (real computation, not keyword equality) | `TextEmbeddingProvider` |
| Image similarity | Pillow: perceptual difference hash + colour histogram comparison. Labelled "visual similarity (colour/structure)" — it is not semantic vision | `ImageEmbeddingProvider` |
| Matching | Weighted sum of signals with **configurable weights**; missing signals are excluded and weights renormalised; explanation lists contributing signals | `MATCH_WEIGHTS` config |
| Verification | Questions built from finder private notes and hidden-feature fields; answers compared by token/fuzzy similarity → advisory score; human decision required | `VerificationEvaluator` |
| Notification | Templated, privacy-safe messages | email provider later |

Every score and the UI carry a disclaimer: _a potential match, not proof of ownership._

## 4. Data model

User, ItemReport, ItemImage, ItemAttribute, MatchCandidate, Verification,
Case, Notification, Message (Communication), AuditLog, Flag (user reports of
abuse). Per the spec, with these additions:
- `ItemReport.private_details` — visible only to the author; used for verification.
- `ItemReport.ai_status` — PENDING / DONE / FAILED (retry allowed).
- `ItemReport.text_embedding` — JSON vector (pgvector column in Postgres later).
- `User.is_active` — admin moderation.

### State machines
- Report: `DRAFT → ACTIVE → POTENTIAL_MATCH → … → RECOVERED / CLOSED / EXPIRED`
- Match/Case: `POTENTIAL_MATCH → VERIFICATION_PENDING → VERIFIED | REJECTED → CONNECTED → RECOVERED → CLOSED`
- Transitions are enforced in one module (`services/state_machine.py`); invalid ones return 409.

## 5. Privacy & security

- Passwords hashed with bcrypt; JWT bearer tokens (short expiry), secret from env.
- Email/phone never returned by public endpoints; other users are shown by display name only.
- Public report view hides `private_details` and exact coordinates (rounded).
- Images saved outside any static folder, served only through an authenticated
  endpoint. Uploads are validated (type, ≤5 MB, real image decode) and **re-encoded
  to strip EXIF/GPS metadata**.
- Object-level authorization on every report/match/case/message endpoint.
- Audit log for login, verification decisions, case transitions and admin actions.
- Flag/report mechanism, plus admin deactivation of reports and users.
- Generic error responses; stack traces only in server logs.
- User data is not used for model training.

## 6. Milestones

| Phase | Deliverable | Done when |
|---|---|---|
| 0 | Inspection + this plan + repo | plan committed |
| 1 | Backend skeleton, DB, auth; Next.js shell with login/register/dashboard | register/login works end-to-end |
| 2 | Reports CRUD, image upload, browse, details | report with photo visible to owner |
| 3 | AI pipeline: understanding, retrieval, matching, explanations | demo pair produces a ranked match |
| 4 | Verification, notifications, case state machine, messaging | owner verified → chat → RECOVERED |
| 5 | Admin dashboard: reports, users, flags, cases, health | admin can moderate |
| 6–7 | Integration + pytest suite incl. E2E scenario | all tests green |
| 8 | Dockerfiles, compose (Postgres+pgvector), README, demo script, seed data | fresh clone runs by following README |

## 7. Decisions

1. **SQLite for local dev, Postgres for deploy.** No Postgres/Docker on the dev
   machine. SQLAlchemy keeps both working; vectors are stored as JSON and compared in
   Python, which is fine at regional MVP scale (hundreds to thousands of reports).
2. **No external AI for now** (team decision). Local algorithms do real computation
   and are labelled honestly. Provider interfaces allow upgrades later.
3. **Human-in-the-loop verification:** the finder confirms the owner's answers;
   the AI score is advisory only.
4. **Local file storage** behind a `StorageService` interface (S3 later).
5. **In-app notifications** first; the email sender is an interface with a
   console/log implementation.
6. **Alembic migrations** run at startup (baseline `0001` + `0002` structured location); pre-migration
   databases are stamped at the baseline and upgraded automatically.
7. **Geographic scope = UET Lahore.** The campus polygon comes from OpenStreetMap; the nearby zone is a 500 m
   buffer. No coordinates are invented: unmapped places are left out until verified. The backend is the
   authoritative geofence check.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Heuristic image similarity is weak on real photos | Low default weight; clear label; vision module plug-in point |
| No Docker locally → deploy config untested here | Compose file kept minimal; test on teammate machine or CI |
| Fraudulent ownership claims | Private-detail questions, human confirmation, rate limiting of verification attempts, audit log |
| Integration with teammates' modules | Stable interfaces in `app/ai/providers`, documented in README |
