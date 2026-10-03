# LostLink AI

AI-assisted regional lost & found. People report lost or found items; LostLink AI
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
  lib/             api client, auth context, types, region config
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
.\.venv\Scripts\python -m pytest -q
```

## Run with Docker (PostgreSQL)

```bash
cp .env.example .env    # set POSTGRES_PASSWORD, JWT_SECRET (32+ chars), optional ADMIN_EMAIL/ADMIN_PASSWORD
docker compose up --build
```

## Demo script (hackathon)

1. `python -m scripts.seed_demo` creates `ayesha@lostlink.demo` (owner), `bilal@lostlink.demo` (finder) and
   `admin@lostlink.demo`, all with password `demo-pass-123`.
2. **Ayesha** → *Report lost item*: "I lost my black backpack near the library at around 3 PM." Add a photo,
   pick **Main Library**, colour *Black*, feature *Red keychain*, private details *what was inside*.
3. **Bilal** (another browser/incognito) → *Report found item*: "I found a black backpack near the library
   around 3:30 PM." Add a photo, pick **Library Courtyard**, private notes *what's inside*.
4. LostLink AI matches automatically → Ayesha gets a notification: *"LostLink AI found a potential match for
   your lost item."* The match page shows the relevance %, reasons (same category, colour, ~0.1 km, ~30 min,
   similar feature) and per-signal bars.
5. Ayesha clicks **Verify ownership** and answers the private questions (bag contents, hidden mark).
6. Bilal is notified, sees her answers plus an **advisory** consistency score, and confirms the owner.
7. A case opens with in-app chat (first names only, no emails or phones). They arrange the handover.
8. Either party clicks **Mark recovered** → case and both reports become **RECOVERED**.
9. `admin@lostlink.demo` → **Admin** shows stats, health, reports, flags, users, cases and audit log.

`python -m scripts.seed_demo --reports` pre-creates the backpack pair if you want to skip steps 2–3.

## How matching works

The **orchestrator** (`app/ai/orchestrator.py`) runs whenever a report is created, edited, or gets a photo,
and on demand via `POST /reports/{id}/match`:

1. **Item understanding** normalises the category (synonym taxonomy) and extracts colours, brand and
   distinctive features. Each attribute is stored with `source = USER | AI` and a confidence.
2. **Embeddings**:
   - Text: hashed word + character-trigram vectors (lexical-semantic similarity, robust to wording).
   - Images: colour histogram + perceptual hash. This is labelled in the UI as colour/shape similarity, not
     object recognition.
3. **Candidate retrieval** filters by opposite type, open status, other users, compatible category group,
   time window (found ≥ lost − 12 h, ≤ lost + 60 days) and radius (30 km), then ranks by text similarity.
4. **Matching** scores category, text, colour, brand, features, image, location (distance decay) and time
   (time decay). Weights live in `app/ai/config.py` and can be overridden by env (`MATCH_WEIGHT_IMAGE=0.2`).
   Missing signals are excluded and the remaining weights renormalised. Contradictions (different category or
   brand) cap or discount the score.
5. Matches ≥ `MATCH_THRESHOLD` (default 0.55) are stored with an explanation, and both parties are notified.

If the pipeline fails, the report is kept, `ai_status = FAILED` is shown, and the user can retry.

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

## Privacy & security

- Passwords: bcrypt. Tokens: JWT (`JWT_SECRET` required and checked in production).
- Other users see first names only. Emails are never returned except to their owner, and are masked for admins.
- `private_details` and exact coordinates are only returned to the report author. Others get ~1 km precision.
- Uploads: type allow-list, 5 MB limit, decoded by Pillow, re-encoded (strips EXIF/GPS), stored outside any
  public folder, served only via 60-minute signed URLs issued to authorised viewers.
- Object-level authorisation on every report/match/case/message endpoint (404 for non-participants).
- Audit log: registration, logins (incl. failures), report changes, verification decisions, case changes,
  admin actions.
- Flag/report mechanism plus admin deactivation of reports and users.
- Generic error messages to clients; stack traces only in server logs.
- User data is not used for model training.

Known MVP limitations: JWT stored in `localStorage` (consider httpOnly cookies), no rate limiting yet, email
notifications are logged rather than sent (`services/notifications.py::send_email`), tables are created on
startup (add Alembic before schema changes in production), and image similarity is a heuristic.

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

- Branches: `main` (always runnable), `develop`, `feature/ai`, `feature/vision`, `feature/frontend`,
  `feature/verification`, `feature/backend`.
- AI and vision: work inside `backend/app/ai/` against the provider interfaces. Keep
  `tests/test_ai_units.py` and `tests/test_e2e_workflow.py` green.
- Frontend: API types live in `frontend/src/lib/types.ts`.
