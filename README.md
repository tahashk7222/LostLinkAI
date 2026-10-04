# LostLink AI

AI-assisted lost & found for the **UET Lahore** community (Main Campus and its immediate surroundings).
People report lost or found items; LostLink AI
understands the reports, finds and ranks potential matches with an explanation,
runs a privacy-preserving ownership verification, and opens controlled in-app
communication once a **human** (the finder) confirms ownership.

> LostLink AI is decision support. A match score is never proof of ownership, and
> no contact details are exchanged by the system.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS 4 |
| Backend | FastAPI, SQLAlchemy 2, Pydantic 2 |
| Database | SQLite (local dev) · PostgreSQL + pgvector image (Docker/prod) |
| AI | Local modules behind provider interfaces (see below) |
| Auth | bcrypt password hashing, JWT bearer tokens |
| Storage | Private local folder, images served via short-lived signed URLs |

## Repository layout

```
backend/
  app/
    ai/            orchestrator, understanding, retrieval, matching, verification, providers/
    api/routes/    auth, reports, matches (+verification), cases (+messages), notifications, images, flags, admin
    services/      reports, matches, storage, notifications, state_machine, audit
    models/        SQLAlchemy entities + enums
    schemas/       Pydantic request/response models
    core/          config, security, errors
  tests/           unit, security and end-to-end tests
  scripts/         seed_demo.py
frontend/src/
  app/             pages (landing, auth, dashboard, report lost/found, browse, details,
                   matches, verify, notifications, cases, chat, profile, admin)
  components/      Nav, ReportForm, MatchCard, shared UI
  lib/             api client, auth context, types, geofence mirror (geo.ts), categories
docs/              IMPLEMENTATION_PLAN.md (architecture, decisions, risks)
```

## Run locally (Windows / PowerShell)

Prerequisites: Python 3.12, Node.js 20+ (24 LTS recommended).

**Quick start** (after the one-time backend setup below): double-click `start-dev.cmd` (or run it from any
terminal). It opens the API and web app in two windows and creates `backend/.env` with a random JWT secret
on first run.

> On Windows with the default *Restricted* execution policy, `npm` inside PowerShell fails ("running scripts is
> disabled"). Use `npm.cmd` instead, or run commands from `cmd`.

**Backend**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # edit JWT_SECRET
.\.venv\Scripts\python -m scripts.seed_demo     # optional demo accounts
.\.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs · health: http://localhost:8000/health

**Frontend**

```powershell
cd frontend
npm install
copy .env.example .env.local
npm run dev
```

Open http://localhost:3000

**Tests**

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q                       # full backend suite (about 70 s)

cd ..\frontend
npm.cmd run typecheck                                     # frontend type check (tsc --noEmit)
```

**Browser checks** (need the API on port 8000 and the web app on port 3000 running; `pip install playwright`
into any Python, and the installed Google Chrome):

```powershell
python frontend\e2e\report_flow.py --api http://localhost:8000 --web http://localhost:3000   # two users, lost → found → match
python frontend\e2e\matching_ui.py --api http://localhost:8000 --web http://localhost:3000   # lead labels, Weak rules, layout
```

Both scripts create their own accounts and reports with a unique suffix. Screenshots go to `frontend/e2e/screenshots`.
Run them against a scratch database, not your working one, because they add test rows.

**Matching evaluation** (synthetic data only; the numbers are not real-world accuracy):

```powershell
cd backend
.\.venv\Scripts\python -m evaluation.run_eval --label my-run --dataset base      # also: extended, targeted, cases
```

## Run with Docker (PostgreSQL)

```bash
cp .env.example .env    # set POSTGRES_PASSWORD, JWT_SECRET (32+ chars), optional ADMIN_EMAIL/ADMIN_PASSWORD
docker compose up --build
```

## Demo script (hackathon)

1. `python -m scripts.seed_demo` creates `ayesha@lostlink.demo` (owner), `bilal@lostlink.demo` (finder) and
   `admin@lostlink.demo`, all with password `demo-pass-123`.
2. **Ayesha** → *Report lost item*: "I lost my black backpack near the Lecture Theatre at around 3 PM." Drop a
   photo in the upload box, pick the **Lecture Theatre** chip (optionally describe the exact spot), colour
   *Black*, feature *Red keychain*, private details *what was inside*.
3. **Bilal** (another browser/incognito) → *Report found item*: "I found a black backpack near the Lecture
   Theatre around 3:30 PM." Add a photo, pick **Allah Wala Chowk** (or *Use my location* / *Pick on map*),
   private notes *what's inside*.
4. LostLink AI matches automatically → Ayesha gets a notification: *"LostLink AI found a potential match for
   your lost item."* The match page shows the relevance %, reasons (same category, colour, distance in metres,
   "Both on UET Lahore campus", ~30 min, similar feature) and per-signal bars.
5. Ayesha clicks **Verify ownership** and answers the private questions (bag contents, hidden mark).
6. Bilal is notified, sees her answers plus an **advisory** consistency score, and confirms the owner.
7. A case opens with in-app chat (first names only, no emails or phones). They arrange the handover.
8. Either party clicks **Mark recovered** → case and both reports become **RECOVERED**.
9. `admin@lostlink.demo` → **Admin** shows stats, health, reports, flags, users, cases and audit log.

`python -m scripts.seed_demo --reports` pre-creates the backpack pair if you want to skip steps 2–3.

## Geographic scope (UET Lahore geofence)

LostLink is limited to **UET Lahore Main Campus** and a **Nearby UET Area** (500 m around the campus boundary).

- Boundary and quick-select places: `backend/app/geo/uet_lahore.json`, one config file shared by backend and
  frontend via `GET /geo/config`. Override the file with `GEOFENCE_FILE`.
  - `campus_polygon`: the campus outline from OpenStreetMap (way 302283434, © OpenStreetMap contributors, ODbL).
  - `nearby_buffer_m`: radius of the nearby zone (500).
  - `places`: only locations whose coordinates come from OpenStreetMap. Each entry records its `source`.
    Some are inferred from mapped road names and are labelled as such. Main Library, Library Courtyard,
    Cafeteria and a "Main Gate" are not mapped in OpenStreetMap, so they are deliberately absent until
    verified pins are added.
- **The backend is authoritative** (`app/services/location.py`). A report needs a predefined place (the server
  uses its own coordinates) or a GPS/map point inside the boundary. The server computes the zone (`campus` /
  `nearby`). Out-of-area points, free text only, and unknown places are rejected with HTTP 422. The frontend
  (`lib/geo.ts`) mirrors the check for instant feedback only.
- Users can describe the exact spot (e.g. "Bench outside the Lecture Theatre") after choosing a place.
- Precise coordinates are used only for validation and matching. Other users see the description and zone.
- Reports created before the geofence keep working and are shown as "Location not verified".

## How matching works

The **orchestrator** (`app/ai/orchestrator.py`) runs whenever a report is created, edited, or gets a photo,
and on demand via `POST /reports/{id}/match`:

1. **Item understanding** (deterministic rules, no learned model): normalises the category (synonyms, including
   common Roman-Urdu words), extracts colours with shades, brands with aliases, model numbers, and typed
   distinctive features (accessory, marking, damage). Each attribute records `source = USER | RULE`, where
   `RULE` means inferred from free text by rules, with a confidence.
2. **Description similarity**: pure-Python BM25 over the free-text description, with category, colour, brand,
   model, feature words, place names and report boilerplate removed, so the same evidence is not counted twice.
   A description with no identity terms gives no signal (absent, not zero). `MATCH_TEXT_METHOD=hashing` restores
   the earlier hashed-vector matcher.
3. **Candidate retrieval** filters by opposite type, open status, other users, compatible category group,
   time window (found ≥ lost − 12 h, ≤ lost + 60 days) and radius (30 km). Every candidate that passes is scored.
4. **Scoring v3** (`app/ai/matching.py`, default). Three things are kept apart: the **relevance** score (ranking), the
   **lead label**, and **notification eligibility**.
   - Identity-bearing groups can qualify a lead: a shared model code, a matching **marking** feature (engraving,
     name, initials, sticker) or **damage** feature (scratch, dent, crack), and a description match after removing
     the report's own brand, colour, category and model words and any accessory wording.
   - Generic attributes only corroborate and never qualify a lead alone: brand, colour, and accessory features
     (keychain, tag, strap, case). A common brand on a key ring is not identity.
   - A lead qualifies with at least one identity group and at least two groups in total. Category, location and time
     never qualify, and a visually similar photo never qualifies.
   - Missing identity evidence lowers the score through a coverage factor. Contradictions cap the score.
   - Labels: **Strong** (≥ 0.75, qualifies, at least three groups, no strong contradiction), **Possible** (qualifies,
     ≥ `MATCH_THRESHOLD`, default 0.55), **Weak** (any identity or generic match, ≥ 0.35: stored and shown, never
     notified, and it cannot start ownership verification).
   - The relevance score is a rule-based value. It is not a probability of ownership.
   - Final safeguards (v3 only; the score is unchanged by them, only the lead and notification):
     - **Identifier conflicts.** When each report states an identifier (a serial, initials, a quoted name) that the other
       does not, the pair is a contradiction and is capped below the threshold. Identical identifiers match.
     - **Colour contradiction.** If both reports state a colour and the colours conflict, the pair does not notify
       unless it has a shared model code or an identifier-matched feature.
     - **Close location for marking or damage.** A marking or damage match alone qualifies for notification only when
       the reports are at the same place or within 250 m (`NEAR_M`, the same "near" distance the app uses for
       labels). Model-code identity is not limited by distance (a documented limitation).
   - `MATCH_SCORER=v2` restores the earlier identity rule (brand plus a description match qualified, and accessory
     features counted as identity). `MATCH_SCORER=v1` restores the earlier weighted score.
5. **Notification**: only Strong and Possible leads (`notify_eligible`) notify, at most 3 per report per run. Weak leads
   are visible to the owner in the match list, at most five before "Show more", with a warning, and do not change
   report status. A Weak lead that later becomes notifiable notifies once.

Each reason and concern is stored as structured **evidence** (`signal`, `text`, `direction`
`supports`/`contradicts`, and a rule-based `strength` of `STRONG`/`MODERATE`/`WEAK`), together with the lead label.

**Stale suggestions.** An uncontested suggestion is withdrawn when it no longer qualifies: the report is
edited so it is no longer a candidate, the score drops below the threshold, either report is closed or
deactivated, or the other report is connected to a different match. Suggestions already in verification
are never withdrawn. Dismissed and rejected pairs are not re-suggested. Matching runs are serialised
within the API process (`MATCHING_LOCK`).

If the pipeline fails, the report is kept, `ai_status = FAILED` is shown, and the user can retry.

Offline evaluation on **synthetic** datasets lives in `backend/evaluation/` (see its README for the metrics,
the limits of the data, and the before/after results).

### Plugging in real models (vision / LLM teams)

Implement the interfaces in `backend/app/ai/providers/`:

- `TextEmbedder.embed(text) -> list[float]` (e.g. OpenAI embeddings, sentence-transformers)
- `ImageEmbedder.embed(PIL.Image) -> dict` and `.similarity(a, b) -> float` (e.g. CLIP)

Return them from `get_text_embedder()` / `get_image_embedder()`. Nothing else needs to change. The
understanding agent (`app/ai/understanding.py`) can likewise be replaced by an LLM extractor. Validate its
output against the same `Understanding` dataclass and keep the rule-based fallback.

## Ownership verification

- The owner starts verification. The **verification agent** picks questions the public listing doesn't answer
  (bag contents, phone case/wallpaper, last 4 of serial, hidden mark…).
- Answers are visible only to the finder, together with an **advisory** score comparing them with the
  finder's private notes. Notes never quote those private details.
- **The finder decides** (accept/reject). Only an accepted verification creates a case and unlocks messaging.
  AI output never authorises access.

State machines (`app/services/state_machine.py`), with invalid transitions returning `409`:

- Match: `POTENTIAL_MATCH → VERIFICATION_PENDING → AWAITING_FINDER_REVIEW → VERIFIED | REJECTED` (or `DISMISSED`)
- Case: `CONNECTED → RECOVERED → CLOSED` (or `CONNECTED → CLOSED`)
- Report: `ACTIVE ⇄ POTENTIAL_MATCH → CONNECTED → RECOVERED → CLOSED`, plus `EXPIRED` and `DEACTIVATED`

## Admin portal

Admins sign in like everyone else. An account with role `ADMIN` sees **Admin** in the navigation. The backend checks the
role on every admin route (401 without a token, 403 for a non-admin), so hiding the page is not the protection.
To create the first admin, set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `backend/.env` before starting the API. Use a real
domain, because reserved domains such as `.test` are rejected.

Pages (`frontend/src/app/admin/`):

- `/admin`: operational cards and recent reports, matches and admin or recovery actions. All numbers come from the API.
  Tabs for reports, verification, flagged content, users, cases and the audit log.
- `/admin/reports/{id}`: review one report. Shows the photo, the public details, the reporter's masked email and the
  extracted attributes, labelled as automated checks. Approve (keeps the report live) or reject with a reason from a
  fixed list and an optional note.
- `/admin/cases/{id}`: recovery confirmation. Shows whether each item is in active listings, eligible for matching and
  archived. Close the case when done.

Lifecycle rules (the same rules the owner and finder use, from `app/services/case_lifecycle.py`):

- Reports go live when created (post-moderation). Rejection moves an open report to `DEACTIVATED`, which takes it out
  of matching at once, and stores the reason. It is refused for a report in a recovery case.
- A recovered item leaves active listings and matching, and is stamped `archived_at`. Nothing is deleted.
- Admin actions and case changes are written to the audit log. The audit entry holds the reason code, never the
  free-text note.
- Verification progress is shown as pending, in progress, verified, failed or cancelled. Owners' answers, questions and
  advisory notes are never returned by admin routes.

New admin endpoints: `GET /admin/dashboard`, `GET /admin/reports/{id}`, `POST /admin/reports/{id}/approve`,
`POST /admin/reports/{id}/reject`, `GET /admin/verification`, `GET /admin/cases/{id}`, `POST /admin/cases/{id}/close`.

Browser walkthrough (needs an admin account; use a scratch database because it adds rows):

```powershell
python frontend\e2e\admin_flow.py --api http://localhost:8000 --web http://localhost:3000 `
  --admin-email admin@example.com --admin-password <password>
```

## Privacy & security

- Passwords: bcrypt. Tokens: JWT (`JWT_SECRET` required and checked in production).
- Other users see first names only. Emails are never returned except to their owner, and are masked for admins.
- `private_details` and coordinates are only returned to the report author. Others see a location
  description and zone, never coordinates.
- Uploads: type allow-list, 5 MB limit, decoded by Pillow, re-encoded (strips EXIF/GPS), stored outside any
  public folder, served only via 60-minute signed URLs issued to authorised viewers.
- Object-level authorisation on every report/match/case/message endpoint (404 for non-participants).
- Audit log: registration, logins (incl. failures), report changes, verification decisions, case changes,
  admin actions.
- Flag/report mechanism plus admin deactivation of reports and users.
- Generic error messages to clients; stack traces only in server logs.
- User data is not used for model training.

Known MVP limitations: matching is serialised per API process only, so multiple API workers need a database-level lock; a withdrawn suggestion's notification link returns 404; JWT stored in `localStorage` (consider httpOnly cookies), no rate limiting yet, email
notifications are logged rather than sent (`services/notifications.py::send_email`), map tiles come from the
public OpenStreetMap tile server (use a tile provider for heavy production use), and image similarity is a
heuristic.

## Database migrations

Schema changes use **Alembic** (`backend/migrations/`). Migrations run automatically on startup
(`app/db/migrate.py`). A database created before migrations existed is detected, stamped at the baseline and
upgraded. To add a migration after changing models:

```powershell
cd backend
.\.venv\Scripts\alembic revision --autogenerate -m "describe change"
```

## API overview

Full interactive docs at `/docs`.

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `GET/PUT /auth/me` |
| Reports | `POST/GET /reports`, `GET/PUT/DELETE /reports/{id}`, `POST /reports/{id}/images`, `DELETE /reports/{id}/images/{image_id}` |
| Matching | `POST /reports/{id}/match`, `GET /reports/{id}/matches`, `GET /matches`, `GET /matches/{id}`, `POST /matches/{id}/dismiss` |
| Verification | `POST /matches/{id}/verification`, `GET /matches/{id}/verification`, `POST /matches/{id}/verification/answers`, `POST /matches/{id}/verify` |
| Cases | `GET /cases`, `GET /cases/{id}`, `PUT /cases/{id}/status`, `GET/POST /cases/{id}/messages` |
| Notifications | `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` |
| Moderation | `POST /flags`, `GET /admin/stats`, `/admin/reports`, `/admin/users`, `/admin/flags`, `/admin/cases`, `/admin/matches`, `/admin/audit` |

## Team integration

Start with **[DEVELOPER_HANDOFF.md](DEVELOPER_HANDOFF.md)**: architecture, entry points, the matching pipeline, what not
to change, and the module boundaries for each teammate.

- The current complete state is on `main`. It must be pushed to `origin` before a fresh clone has it.
- Suggested branches for each module: `feature/vision`, `feature/frontend`, `feature/verification`, `feature/qa`.
  Branch from `main` once it is pushed, and keep commits focused.
- Keep `backend/tests/test_ai_units.py` and `backend/tests/test_e2e_workflow.py` green. Run the full suite before each merge.
- Frontend: API types live in `frontend/src/lib/types.ts`. HTTP calls go through `frontend/src/lib/api.ts`.
