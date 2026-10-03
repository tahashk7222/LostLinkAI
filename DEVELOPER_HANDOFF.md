# LostLink AI: developer handoff

Read this first, then the README for setup details.

> **Before teammates start:** the complete current state is on local `main`, which is **26 commits ahead of
> `origin/main`**. `origin/main` and `origin/develop` both still point at `d6c7939`, which does not have the matching
> work. Nothing has been pushed. Until the owner pushes, a fresh clone will not match this document. See "Blocker" in
> the handoff report.
Nothing in this document describes a feature that is not in the repository.

## 1. Current architecture

```
Browser (Next.js 15, React 19, TypeScript)           frontend/src
   │  JSON over HTTP, Bearer token in localStorage
   ▼
FastAPI API (Python 3.12, SQLAlchemy 2, Alembic)      backend/app
   ├── api/routes        HTTP endpoints (thin)
   ├── services          reports, matches, notifications, audit, state machine, match lifecycle
   ├── ai/               item understanding, retrieval, scoring, orchestrator, verification questions
   ├── geo/              UET Lahore geofence (uet_lahore.json) and distance helpers
   ├── models / schemas  database tables and request/response shapes
   └── db                session, Base, migration runner
   │
   ▼
SQLite locally (backend/lostlink.db) · PostgreSQL in Docker (docker-compose.yml)
Uploads: private storage (STORAGE_DIR), served only through authenticated endpoints
```

There is one matching implementation, in `backend/app/ai/`. The evaluation harness (`backend/evaluation/`) calls the
same code path. Do not write a second scorer.

## 2. Backend entry points

| Path | Purpose |
|---|---|
| `backend/app/main.py` | App factory, routers, error handlers, startup (migrations, optional admin) |
| `backend/app/api/routes/*.py` | `auth`, `reports`, `images`, `matches`, `cases`, `notifications`, `geo`, `flags`, `admin` |
| `backend/app/api/deps.py` | `CurrentUser`, `DB` dependencies |
| `backend/app/core/config.py` | Settings from environment variables (`.env`) |
| `backend/app/ai/orchestrator.py` | Runs the matching pipeline for one report (`process_report`, `run_matching`) |
| `backend/app/services/match_lifecycle.py` | Withdraws stale matches, reopens reports |
| `backend/scripts/seed_demo.py` | Optional demo accounts (`python -m scripts.seed_demo`) |

## 3. Frontend entry points

| Path | Purpose |
|---|---|
| `frontend/src/app/` | App Router pages: `login`, `register`, `report/lost`, `report/found`, `reports/[id]`, `matches`, `matches/[id]`, `matches/[id]/verify`, `cases`, `notifications`, `profile`, `admin` |
| `frontend/src/lib/api.ts` | The only HTTP client. Errors come back as `ApiError` with the server's `detail` |
| `frontend/src/lib/auth.tsx` | Session and token handling |
| `frontend/src/lib/types.ts` | API types (update here when an endpoint changes) |
| `frontend/src/components/ReportForm.tsx` | Lost and found report form, photo upload, location |
| `frontend/src/components/LocationPicker.tsx` | UET Lahore places, GPS and map selection, validation feedback |
| `frontend/src/components/MatchEvidence.tsx`, `MatchCard.tsx` | Strong, Possible and Weak labels, evidence, Weak-lead warnings |

## 4. Database and migrations

- Models are in `backend/app/models/`. Migrations are in `backend/migrations/versions/` (Alembic, revisions 0001 to 0005).
- Migrations run automatically at startup (`backend/app/db/migrate.py`). A database created before migrations is stamped
  at the baseline and upgraded.
- To change the schema: edit the model, then `alembic revision --autogenerate -m "..."` from `backend/`. Review the file.
  Never edit a revision that has already been applied anywhere.
- Migration 0004 relabels attribute sources and uses `ALTER TYPE` on PostgreSQL. It has been tested on SQLite only.

## 5. Matching pipeline

```
REPORT → item understanding (rules: category, colour, brand, model, typed features, identifiers)
       → candidate retrieval (opposite type, open, other users, category group, time window, 30 km)
       → relevance score (weighted signals; a ranking value, not a probability)
       → evidence analysis (identity groups, corroborating attributes, contradictions)
       → lead: STRONG / POSSIBLE / WEAK / none
       → notification eligibility (STRONG and POSSIBLE only; at most 3 per report per run)
       → human ownership verification (Weak leads cannot start it)
       → recovery (case and messages)
```

Keep the three values separate: `score` ranks, `lead` classifies the evidence, `notify_eligible` is the notification
policy. The hardening rules (identifier conflicts, colour contradiction, close location for marking or damage) are
described in the README under "How matching works". Scoring history is in `backend/evaluation/README.md`.

## 6. Important APIs

Full interactive docs at `http://localhost:8000/docs`. Summary:

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `GET/PUT /auth/me` |
| Reports | `POST/GET /reports`, `GET/PUT/DELETE /reports/{id}`, `POST /reports/{id}/images` |
| Matching | `POST /reports/{id}/match`, `GET /reports/{id}/matches`, `GET /matches`, `GET /matches/{id}`, `POST /matches/{id}/dismiss` |
| Verification | `POST /matches/{id}/verification`, `POST /matches/{id}/verification/answers`, `POST /matches/{id}/verify` (finder decides) |
| Cases | `GET /cases`, `GET /cases/{id}`, `PUT /cases/{id}/status`, `GET/POST /cases/{id}/messages` |
| Notifications | `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` |
| Geo | `GET /geo/config` (the UET Lahore place list and the geofence) |
| Moderation | `POST /flags`, `/admin/*` (admin role only) |

## 7. How to run locally

**Windows, one step:** double-click `start-dev.cmd` (creates `backend/.env` with a random secret on first run).

**Manually** (PowerShell, from the repository root):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\uvicorn app.main:app --reload --port 8000

cd ..\frontend
npm.cmd install
copy .env.example .env.local
npm.cmd run dev        # http://localhost:3000
```

Optional demo data: `cd backend; .\.venv\Scripts\python -m scripts.seed_demo`.

Environment variables are listed in `backend/.env.example` and `frontend/.env.example`. The important ones:
`JWT_SECRET` (must be replaced outside development), `DATABASE_URL`, `CORS_ORIGINS`, `STORAGE_DIR`, `MATCH_THRESHOLD`,
and `NEXT_PUBLIC_API_URL` for the frontend. Docker uses `docker-compose.yml` with PostgreSQL (see README).

## 8. How to test

| Check | Command | Expected |
|---|---|---|
| Backend suite | `cd backend; .\.venv\Scripts\python -m pytest -q` | all pass (134 at handoff) |
| Frontend types | `cd frontend; npm.cmd run typecheck` | exit 0 |
| Frontend build | `cd frontend; npm.cmd run build` | builds all routes |
| Browser: report flow | `python frontend\e2e\report_flow.py --api ... --web ...` | passes; needs Playwright and Chrome |
| Browser: matching UI | `python frontend\e2e\matching_ui.py --api ... --web ...` | passes |
| Evaluation (synthetic) | `cd backend; .\.venv\Scripts\python -m evaluation.run_eval --label X --dataset base` | writes `evaluation/results/X.json` |

Run the browser scripts against a scratch database. They add rows. Do not run `npm run build` in a folder while its
`next dev` server is running, because the build corrupts `.next`. Copy the folder first, as was done for the final check.

## 9. What NOT to modify

- **Matching rules**: the threshold (`MATCH_THRESHOLD`, default 0.55), the weights, the two-group qualification rule,
  the accessory policy (accessories are corroborating, `tag` is an accessory, `name tag` is a marking), the lead
  definitions, and the notification policy. These are frozen. Changes need a documented evaluation, not a tweak.
- **Evaluation history**: everything in `backend/evaluation/results/` and the datasets in `backend/evaluation/data/`.
  Add new files under new labels. Do not overwrite.
- **Applied migrations**: never edit a revision that has run anywhere.
- **Verification**: ownership is decided by people. Do not add automatic approval, and do not let a Weak lead start verification.
- **Privacy**: private details and exact coordinates must never appear in another user's responses or in match explanations.
  `backend/tests/test_match_privacy.py` and the browser canary checks guard this.
- **The geofence data** (`backend/app/geo/uet_lahore.json`) without a review of the campus boundary.

## 10. Suggested module boundaries

Each area can work in parallel. Keep to the boundary, and go through `develop` with focused commits.

| Module | Owns | Starting points | Must keep green |
|---|---|---|---|
| **Computer Vision** | Photo handling and image similarity. Real image models would replace the heuristic embedder behind `app/ai/providers/`. | `backend/app/ai/providers/image.py`, `backend/app/api/routes/images.py` | `test_reports_security.py` (upload validation), `test_e2e_workflow.py`. No new paid APIs, and no new models without a decision |
| **Frontend / UI** | Pages and components, accessibility, mobile layout, error messages | `frontend/src/app/`, `frontend/src/components/`, `frontend/e2e/` | `npm run typecheck`, `npm run build`, both browser scripts |
| **Verification and notifications** | Ownership questions, finder review, cases and messages, notification delivery (`send_email` is currently a log stub) | `backend/app/ai/verification.py`, `backend/app/services/notifications.py`, `backend/app/api/routes/matches.py`, `cases.py` | `test_e2e_workflow.py`, `test_matching_lifecycle.py`, `test_state_machine.py` |
| **QA and documentation** | Test coverage, browser checks, README and this file, evaluation reports (labelled synthetic) | `backend/tests/`, `frontend/e2e/`, `backend/evaluation/README.md` | the full suite must pass before each merge |

The matching core (`backend/app/ai/matching.py`, `understanding.py`, `orchestrator.py`) is owned by the matching author.
Other modules should call it through `score_candidates` and `run_matching`, not reimplement it.

## Known limitations

- **Matching recall is low by design.** On the synthetic base set, v3 notifies 14% of true pairs. Most true pairs share only
  colour, brand or place, and the rules deliberately treat those as Weak. Do not lower the threshold to fix this.
- **Model-code identity ignores distance.** An engraved code such as `AK-19` can read as a model, so distant items can
  notify. This is documented and not fixed.
- **Identifier checks cover digits, quoted names and initials only.** They do not parse free-text names.
- **Close location uses 250 m.** Real GPS error may be larger, so some true marking matches become Weak.
- **Synthetic evaluation only.** Every metric in `evaluation/` describes synthetic data, not real reports.
- **Image similarity is a heuristic** (colour and silhouette), not object recognition.
- **Notifications are logged, not emailed** (`services/notifications.py`).
- **Matching is serialised per API process.** Several API workers need a database-level lock.
- **Tokens are stored in `localStorage`**, and there is no rate limiting yet.
- **PostgreSQL and Docker were not run in the final check.** Migrations were tested on SQLite only.
- **The browser checks do not complete verification or recovery.** The backend workflow test covers accept and messages.
- **Weak leads are not capped in the API.** The UI shows five at a time.
- **Roman-Urdu vocabulary is small** and not evaluated on real text.
