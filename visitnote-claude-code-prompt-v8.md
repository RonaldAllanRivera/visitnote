# VisitNote AI — Build Specification

> **v8.** Supersedes v7. See `SPEC-CHANGELOG.md` for what changed and why.

## Project Overview

Build the MVP of **VisitNote AI**, a SaaS that converts recorded audio from home care and home health visits into structured, compliance-ready documentation. Two note formats ship on day 1:

- **Shift Note (Tier 1)**: caregivers, home health aides, CNAs. Non-clinical daily care documentation.
- **Skilled Nursing Note, SOAPIE (Tier 2)**: RNs/LPNs doing home health visits under Medicare-style documentation standards.

Flow: the user records or uploads audio (a live visit with consent, or a spoken recap dictated after the visit), the backend transcribes it, an LLM structures it into the selected note format and flags missing or non-compliant elements, and the user reviews, edits, signs off, and exports as PDF or shares a read-only link. Agencies supervising multiple caregivers get a web dashboard with a review queue and compliance analytics. The operator (me) runs payments and support from a staff-only operations console.

**Capture ships on web first, then mobile.** The React SPA is the day-1 field client using `MediaRecorder`; the React Native app follows and reuses the same API. This is a sequencing decision, not a scope reduction — both clients are in scope.

## Architecture (monorepo, one API, two clients)

```
visitnote/
  backend/    FastAPI API + arq worker (same image) — Oracle Cloud ARM VM, Docker
  web/        React 19 + Vite SPA: landing, capture, review, agency dashboard, operator console, share pages — Cloudflare Pages
  mobile/     React Native (Expo): the native field client for caregivers and nurses (built after web capture works)
  docker-compose.yml        local dev: api + worker + redis + postgres
  docker-compose.prod.yml   production: pulls images from GHCR, adds Caddy for TLS
  .github/workflows/        CI: ruff/mypy/pytest, tsc/vitest, jest; multi-arch build + SSH deploy
```

The FastAPI backend is the ONLY thing that talks to the database. Both clients are consumers of one versioned REST API and generate typed clients from its OpenAPI schema.

### backend/ (FastAPI)
- Python 3.12, FastAPI, Pydantic v2 for every request/response model, async SQLAlchemy 2.0 with asyncpg, **Alembic** migrations
- Layered structure: `routers/` (HTTP only) -> `services/` (business logic) -> `repositories/` (DB access). Routers never touch the session directly; dependency injection via `Depends` for session, current user, entitlements
- Auth built in-house: argon2 password hashing (`argon2-cffi`), short-lived JWT access tokens (`pyjwt`) + rotating refresh tokens stored hashed in a `refresh_tokens` table (reuse detection revokes the family), Google sign-in via `authlib` OAuth
- Background jobs: **arq** (Redis-based, async-native, fits FastAPI) for the pipeline, plus arq cron jobs for scheduled tasks
- Storage: Cloudflare R2 via `aioboto3` (S3-compatible), private bucket, presigned URLs for upload and download
- Rate limiting: `slowapi` on auth, share, payment submission, and analytics routes
- OpenAPI served at `/api/v1/openapi.json`; clients generate types with `openapi-typescript`
- PDF export: WeasyPrint, rendered from Jinja2 templates per note format
- **All timestamps are stored in UTC** (`TIMESTAMPTZ`), never naive. See Time and Timezones.

### web/ (React + Vite)
- React 19, Vite, TypeScript strict, React Router v7 (data routers), **TanStack Query** for all server state, **Zustand** for client state (auth session, dashboard filters, UI)
- Tailwind CSS v4 + shadcn/ui components; **Recharts** for analytics charts
- React Hook Form + Zod for forms
- Typed API client generated from the FastAPI OpenAPI schema (`openapi-typescript` + `openapi-fetch`), so backend contract changes surface as type errors
- **Audio capture in the browser**: `navigator.mediaDevices.getUserMedia` + `MediaRecorder` (webm/opus where supported, mp4/aac on Safari), with a Wake Lock (`navigator.wakeLock`) held during recording and a visible warning that browser capture stops if the tab is closed. This is the day-1 field client and the reason the product is demoable from a URL
- Five zones in one SPA: public marketing, public share pages, capture + review (field client), agency dashboard (customer), operator console (staff only)

### mobile/ (React Native)
- Expo (TypeScript, Expo Router), `expo-audio` for recording, `expo-secure-store` for tokens, TanStack Query, same generated API types as web
- Built after the web client works end to end. Its distinct value over web capture is true background and lock-screen recording, which browsers cannot do reliably
- EAS Build profiles for dev/preview/production; Android-first beta

## Two distinct admin surfaces (do not conflate)

1. **Operator console** (`/ops/*` in the web app): used only by staff users (me). Approve/reject GCash payments, inspect failed pipeline jobs, look up users and subscriptions, edit Plans and PaymentSettings. Gated by `is_staff` on the server for every `/api/v1/ops/*` route, not just hidden in the UI.
2. **Agency dashboard** (`/app/*` in the web app): a PAID customer feature for agency owners and supervisors managing their own caregivers. Agency owners have zero staff privileges.

The operator console is a small, purpose-built set of React pages.

## Deployment Targets (all free tier except domain)

- **api + worker + Redis** -> single **Oracle Cloud Always Free ARM VM** (VM.Standard.A1.Flex, 2 to 4 OCPUs / 12 to 24GB, Ubuntu 24, US home region) running docker-compose.prod.yml with Caddy
- **PostgreSQL** -> managed Postgres free tier (Supabase or Neon, used purely as Postgres via a DATABASE_URL; no vendor SDKs), US region
- **Audio + receipts** -> Cloudflare R2
- **web/** -> Cloudflare Pages (static build, SPA fallback to index.html)
- **mobile/** -> Expo EAS free tier; Android internal distribution for beta (iOS deferred; requires a paid Apple Developer account)
- Email -> Resend or Brevo free tier via a small `EmailSender` interface
- Monitoring -> Sentry (FastAPI + arq integrations) and an external uptime ping on `/healthz`
- LLM observability -> **Langfuse Cloud free tier by default**; self-hosting on the VM is a documented optional path (see LLM Observability)

### Hosting fallback is a first-class requirement, not a footnote

Oracle Always Free ARM capacity is frequently unavailable in a given region, and idle Always Free instances can be reclaimed. A demo link that 404s during a job application is a total loss. Therefore:

- `README-deploy.md` must document a **named paid fallback** (Hetzner CX22 at roughly €4/month, or equivalent) with the exact same `docker-compose.prod.yml`, and the deploy must be verified at least once against a non-Oracle host before the project is called done
- No Oracle-specific dependency anywhere. Provider portability is a hard requirement, and it is tested, not asserted

### Containers on the VM (docker-compose.prod.yml)

| Service | Command | Notes |
|---|---|---|
| `caddy` | Caddy with a Caddyfile | Only service publishing 80/443; automatic TLS for the API domain; reverse_proxy to api:8000 |
| `api` | `gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers 3 --bind 0.0.0.0:8000 --timeout 120` | No published host port; `--proxy-headers` equivalent via `forwarded_allow_ips` so client IPs and https scheme are correct behind Caddy |
| `worker` | `arq app.worker.WorkerSettings` | ffmpeg installed in the image; **`max_jobs=2` to bound CPU contention with the API container on a 2-OCPU VM and to stay inside upstream transcription/LLM concurrency limits** (ffmpeg streams audio, so these jobs are CPU- and I/O-bound, not memory-bound); also runs arq cron jobs |
| `redis` | redis:7-alpine, persistence off | Broker only, no published port |

All services `restart: unless-stopped`, internal Docker network, config from one `.env` on the server (never committed). Exactly one worker container, so cron jobs never double-run.

### Production settings (pydantic-settings, `app/core/config.py`)
- All secrets from environment: JWT secret, DATABASE_URL, REDIS_URL, R2 credentials, Deepgram and Anthropic keys, LLM provider and model id, Langfuse keys and host, Sentry DSN, email API key
- CORS restricted to the Cloudflare Pages domain(s); JWT sent in the Authorization header, no cookies
- Trusted host middleware for the API domain; HTTPS enforced by Caddy
- Nothing written to local disk except `/tmp` scratch for ffmpeg, deleted in a `finally` block after every job
- Structured JSON logging to stdout
- `/healthz` checks DB and Redis; used by Docker healthchecks and uptime monitoring

### Deploy workflow (.github/workflows/deploy.yml)
1. On push to main: ruff, mypy, pytest; build a multi-arch image (`docker buildx`, amd64 + arm64) with Actions cache; push to GHCR tagged `latest` and the commit SHA
2. SSH to the VM (`appleboy/ssh-action`): `docker compose pull`
3. **Run migrations as a one-off container before the new app starts**: `docker compose run --rm api alembic upgrade head`. Never run migrations on container startup
4. `docker compose up -d`
5. Poll `/healthz` until green; fail the job otherwise
6. Separate `workflow_dispatch` workflow for one-off commands (e.g. `python -m app.cli create-staff-user`, `python -m app.cli seed-demo`)

### deploy/ folder
- `bootstrap.sh`: install Docker + compose plugin, create the app user, configure UFW, **and fix Oracle Ubuntu images' default iptables REJECT rules** (Oracle blocks ports at the OS level in addition to the VCN Security List; both layers must allow 80/443)
- `deploy.sh`: pull, migrate, up -d, healthcheck (identical to CI, so deploys are reproducible by hand)
- `backup.sh`: nightly `pg_dump` compressed and uploaded to R2 with 14-day retention, installed via cron
- `README-deploy.md`: VM shape and US home region, VCN ingress rules, DNS records, first-deploy checklist, the named paid fallback host, and the same steps for any other VPS
- **Stateless, disposable server; provider portability is a hard requirement**: the same compose file runs unchanged on any VPS; no Oracle-specific dependencies anywhere

## Time and Timezones

A product whose most severe flag is a missing shift time cannot be timezone-naive. This is a correctness requirement, not a polish item.

- Every timestamp column is `TIMESTAMPTZ` and every value stored is UTC. No naive datetimes anywhere, enforced by a mypy-visible `UtcDateTime` type alias and a test
- `visits.timezone` stores the capturing user's IANA zone (e.g. `America/Los_Angeles`), captured from the client at visit creation. All rendering — note body, PDF, dashboard, exports — uses that zone, not the viewer's
- **Overnight shifts are the normal case, not an edge case.** A shift recorded as 22:00–06:00 spans midnight. Duration is computed from full UTC instants, never by subtracting clock times; a naive implementation yields negative duration and a spurious `MISSING_SHIFT_TIMES`. There is a required test for the 22:00–06:00 case and for a shift crossing a DST transition
- Analytics bucketing (per day, per week, day-of-week x hour heatmap) is computed in the agency's configured timezone, so "Monday" means the agency's Monday

## Core Capture Flow (web first, then mobile)

Identical API for both clients. Steps marked *(mobile only)* are deferred to the mobile phase.

1. Sign up (email or Google); onboarding asks role (Caregiver/HHA/CNA vs RN/LPN) setting the default note format (changeable per visit), and captures the user's timezone
2. A 14-day trial starts automatically at signup; no payment details collected
3. Home -> "New Note" -> choose format (Shift Note or SOAPIE) -> choose capture mode
4. Capture modes: **live_audio** (records the visit; tap-to-confirm consent screen logged to consent_logs) or **spoken_recap** (user dictates a post-visit summary; mode acknowledgment logged, no client audio)
5. Record — web: `MediaRecorder` with a Wake Lock and an explicit "do not close this tab" warning; *(mobile only)* `expo-audio` (m4a, max 90 min) surviving backgrounding and screen lock, with documented iOS/Android permission strings. Or pick a file (m4a, mp3, wav, webm; max 200MB)
6. **Upload**: the app requests upload credentials and uploads directly to R2.
   - Files under ~10MB: a single presigned PUT
   - Files over ~10MB: **R2 multipart upload** — the API mints presigned URLs per part, the client uploads parts with individual retry and resumes from the last completed part after a network drop, then calls a complete-upload endpoint. Field staff upload over cellular; a 90-minute recording that fails at 95% of a single PUT is unacceptable
7. API creates the visit and enqueues the arq pipeline; app polls status: Uploading, Transcribing, Generating note, Ready (3s poll with backoff)
8. Review: per-section editable note + Flags panel grouped by severity (critical first), each flag jumping to its section
9. Sign off (locks note, records signer + timestamp) -> PDF export, copy text, or create an expiring read-only share link
10. When the trial ends or a quota/format gate is hit, the Upgrade screen shows GCash payment instructions and a payment submission form (see Billing)
11. Raw audio auto-deletes 24h after sign-off (arq cron); transcript and note retained

### Visit creation is idempotent

The client generates a UUID `idempotency_key` per capture attempt and sends it on visit creation. The API stores it uniquely per user and returns the existing visit on replay. Without this, a retry on a flaky connection creates a duplicate visit and burns a second unit of the user's monthly quota for one piece of work.

## Web App (web/) — five zones

### 1. Public marketing
- `/` landing: headline "Turn your visit into a finished, compliant note in 2 minutes", audience panels (Caregivers / Nurses / Agencies), how-it-works, pricing rendered from the plans API, FAQ (consent, privacy, audio deletion, HIPAA posture), a **"Try the demo"** button (see below), Android download CTA once mobile ships, agency demo request form

#### The public demo (build this; it is not optional polish)
A hiring manager or a prospective agency owner will not sign up. `POST /api/v1/auth/demo` issues a short-lived token for a **read-only seeded demo agency** populated by the seed CLI. Read-only is enforced server side by a `is_demo` flag on the user that rejects every write, not by hiding buttons. The landing page also links one permanent public `/share/:token` sample note so the output is visible with zero clicks.

### 2. Public share pages
- `/share/:token` read-only note view (token-gated public endpoint, throttled, no auth)

### 3. Capture and review (the field client)
- `/app/new`: format + capture mode selection, consent gate, `MediaRecorder` recording with level meter and elapsed time, upload progress with per-part retry, processing status
- `/app/notes/:id/review`: section editor rendered from `section_schema` (no format-specific components), flags panel grouped by severity, sign-off, PDF export

### 4. Agency dashboard (authenticated, agency plan only) — the charting showcase
- `/app/overview`: KPI cards (notes this period, awaiting review, average flags per note, critical-flag rate, average time from visit to signed) plus Recharts:
  - **Line chart**: notes per day over the selected range, with a second series for critical flags
  - **Stacked bar chart**: flag counts by code per week (which requirement is chronically missed)
  - **Horizontal bar chart**: average flags per note by staff member (who needs coaching)
  - **Donut**: note mix (shift_note vs soapie) and review status breakdown
  - **Heatmap grid** (custom component on a CSS grid): submissions by day-of-week x hour, bucketed in the agency's timezone
  - Filters (date range, staff) synced to URL search params so dashboard views are bookmarkable and shareable
- `/app/review`: review queue filterable by severity, format, staff, date; bulk export; open a note read-only with flags; supervisor comments requesting corrections
- `/app/staff`: roster (invite by email, role, active/inactive) and per-staff drill-down with that member's trend charts
- `/app/notes/:id`: full note view with flags, audit trail, share/export
- `/app/settings`: agency profile, timezone, plan and seats, subscription status and period end, payment submission history, data deletion request
- Individual (non-agency) Nurse plan subscribers get a thin `/app/notes` view to read and export their own notes

### 5. Operator console (staff only)
- `/ops/payments`: pending GCash submissions queue (reference number, amount, sender, receipt image preview via presigned URL, plan requested), Approve / Reject with reason; approved and rejected history
- `/ops/jobs`: failed and stuck pipeline jobs with error messages and a retry action
- `/ops/users`: search users and agencies, view subscription and entitlement state, manually extend or cancel a subscription with a required note
- `/ops/settings`: edit Plans (prices, quotas, formats) and PaymentSettings (GCash name, number, QR image, instructions)
- `/ops/prompts`: each template's prompt versions with their eval results side by side (flag F1, critical recall, fabrication count, cost and latency per note), a chart of metrics across versions, the active version highlighted, and a Promote action that is disabled unless the version has a passing eval run
- `/ops/costs`: average and total LLM plus transcription cost per note, per day, and per plan, compared against plan revenue, so margin is always visible
- Every ops action writes an audit log entry with the acting staff user

### Web implementation requirements
- TypeScript strict, function components and hooks only
- All server state through TanStack Query with query key factories per resource; no fetch inside useEffect
- Route loaders/guards for auth, plan entitlement (agency routes show an upgrade screen for individual plans), and staff role (`/ops` returns 404-style not found for non-staff)
- Access token in memory, refresh token handled via a secure refresh flow; automatic silent refresh with request retry on 401
- Charts responsive, light/dark aware, loading skeletons, and an empty state instead of a chart with zero data; each chart has a "view as table" toggle for accessibility
- Code-split each zone (lazy routes) so the landing page stays small

## Note Format 1: Shift Note (caregiver tier)

Sections in order:
1. Shift details: client label, date, start time, end time (extracted if stated, else flagged)
2. Care provided (ADLs): hygiene (bathing, grooming, dressing), toileting, mobility/transfers, meals prepared and eaten, hydration
3. Medications: reminders or administrations, times, missed/refused doses
4. Vitals (only if stated in audio)
5. Observations: mood, mobility, appetite, skin, pain complaints, confusion level; factual only
6. Changes from baseline
7. Incidents: falls, refusals, injuries, unusual events
8. Tasks not completed: what was skipped and the stated reason
9. Handover: forward-looking notes for the next caregiver

### Shift Note flags (implement exactly)
- MISSING_SHIFT_TIMES (critical): start or end time not stated
- MISSING_ADLS (warning): no hygiene, meals, or mobility assistance mentioned
- MISSING_MEDS (warning): no medication statement
- MISSING_INTAKE (warning): no food or fluid intake mentioned
- UNREPORTED_CHANGE (critical): transcript mentions a fall, new pain, new confusion, or skin change not captured in incidents/changes sections
- MISSING_HANDOVER (warning): no forward-looking note
- INCOMPLETE_TASK_UNEXPLAINED (warning): task described as not done with no reason
- VAGUE_LANGUAGE (warning): audio only contained vague phrasing for a section
- NOTE_CONTAINS_VENTING (info): interpersonal complaints detected and omitted
- UNATTRIBUTED_STATEMENT (warning): a reported statement could not be attributed to a speaker (see Speaker Attribution)

## Note Format 2: Skilled Nursing Note, SOAPIE (nurse tier)

Sections in order:
1. Visit details: patient label, visit date, exact arrival time, exact departure time
2. Subjective: patient/caregiver reported status, symptoms, concerns; patient's own words quoted
3. Objective: vital signs, exam findings, measurable data (wound dimensions, stage, drainage character), home environment/safety observations
4. Assessment: clinical assessment tied to diagnosis; progress or change since last visit
5. Plan: plan for next visit with rationale; discharge trajectory; ongoing need for skilled care
6. Intervention: skilled services performed (wound care, medication reconciliation/management, teaching with learner response and return demonstration, skilled observation/assessment, injections/IV) and WHY each required a licensed nurse
7. Evaluation: patient/caregiver response to interventions, measurable where possible; progress toward plan-of-care goals
8. Homebound status: patient-specific statement of why the patient cannot leave home
9. Coordination of care: physician/PT/OT/SLP/MSW/aide/family communication; new orders
10. Medication review: medications reviewed/reconciled this visit, plus issues

### SOAPIE flags (implement exactly)
- Critical: MISSING_VITALS, MISSING_VISIT_TIMES, MISSING_SKILLED_SERVICE, MISSING_NECESSITY_RATIONALE, MISSING_HOMEBOUND, UNREPORTED_CHANGE
- Warning: MISSING_RESPONSE, MISSING_MED_REVIEW, MISSING_POC_LINK, MISSING_NEXT_VISIT_PLAN, MISSING_COORDINATION, VAGUE_LANGUAGE, UNATTRIBUTED_STATEMENT
- Info: MISSING_EDUCATION_RESPONSE, MISSING_PAIN_ASSESSMENT

(Semantics: MISSING_NECESSITY_RATIONALE = intervention named but no statement of why a nurse was required; MISSING_COORDINATION = transcript indicates a reportable change but no physician/team communication documented; UNATTRIBUTED_STATEMENT = see below.)

## Speaker Attribution (transcription must be diarized)

A home visit has at least two speakers — the nurse or caregiver, the client, and often a family member. Both prompts require the patient's own words to be quoted, and the whole product forbids fabrication. **Attributing a quote to the wrong speaker is a fabrication, and it is the easiest one to commit.** Therefore:

- Transcription runs with **diarization enabled**, and the transcript is persisted as ordered speaker turns (`speaker_label`, `start_ms`, `end_ms`, `text`), not as one flat string. `transcripts.raw_text` remains for display and the fabrication checker; `transcripts.turns JSONB` carries the structure
- The LLM receives the turn-structured transcript, with a role hint mapping the recording user to their speaker label where confidently inferable (typically the first or dominant speaker)
- **Prompt rule**: a statement whose speaker cannot be determined is never placed in Subjective as a patient quote. It goes into the note as an unattributed observation and raises `UNATTRIBUTED_STATEMENT`. Guessing is forbidden
- The fabrication checker treats a quoted string attributed to the patient as failing unless it appears in a turn assigned to a non-recording speaker
- At least three golden dataset cases exercise multi-speaker transcripts, including one where a family member reports a symptom the patient does not confirm

## LLM Note Generation (backend/app/llm/: templates.py, shift_note.py, soapie.py, pipeline.py)

Shared rules for both prompts, mandatory:
- **Never invent information.** No transcript support for a section = null section + matching flag. Fabrication is the worst failure; in the nurse tier it is a billing and legal risk.
- **Factual, not interpretive.** Correct: "Patient refused lunch and stated 'I'm not hungry.'" Wrong: "Patient appeared moody." Preserve the speaker's words in quotes for subjective statements, and only where the speaker is known.
- **Banned phrases** (never output; rewrite with specifics or flag): "doing well", "no issues", "seemed fine", "a little off", "stable" without supporting data, "routine visit", "routine check-up", "care provided as ordered"
- Specificity: measurable statements ("ate half of lunch", "wound 2x3 cm, Stage II", "more confused after 8pm")
- No venting; omit and flag

SOAPIE-specific:
- System role: clinical documentation assistant producing Medicare-compliant SOAPIE skilled nursing notes
- Every Intervention pairs the service with a necessity rationale; absent rationale -> list the service + MISSING_NECESSITY_RATIONALE, never invent one
- Professional terminology, but never upgrade clinical severity or certainty beyond the transcript
- Homebound: only from transcript content; never boilerplate

Output contract (both formats), validated with Pydantic against the active note template's schema; on validation failure retry once with a repair instruction, then mark the job failed:
{ "visit_details": {...}, "sections": {format-specific keys, string|null}, "flags": [{"code","message","severity": "info|warning|critical"}] }

Pipeline (arq task): download audio from R2 -> normalize with ffmpeg (mono, 16kHz) -> **diarized transcription** (behind a `TranscriptionProvider` protocol) -> template-driven note generation through an `LLMProvider` protocol (ONE pipeline for both formats) -> flag evaluation -> persist note + normalized `note_flags` rows in one transaction. Retries with exponential backoff, max 3 attempts, then `failed` with the error recorded. **Record per-note cost** (audio minutes, input/output tokens, computed USD) on the job so margin is visible in the operator console.

### Model IDs live in configuration only — this is a hard rule
No model identifier string appears in pipeline, service, or router code. The provider and model come from `app/core/config.py` defaults, overridden per template by `note_templates.llm_provider` / `note_templates.model_id`. Defaults at time of writing:

- LLM: **`claude-sonnet-5`** (Anthropic). *v7 specified `claude-sonnet-4-6`, which is superseded.*
- Transcription: Deepgram — **verify the current recommended model at build time** (`nova-3` if generally available, else `nova-2`) rather than copying a string from this document. Model lineups move faster than specifications do; that is precisely why the provider layer exists

Every generated note records the provider, model id, and prompt version that produced it, so a model change is always traceable.

## LLM Provider Layer (backend/app/llm/providers/)

- `LLMProvider` protocol with one method that takes a system prompt, user content, and an output schema, and returns validated structured output plus usage (input tokens, output tokens, latency, model id)
- `AnthropicProvider` is the default implementation. The active provider and model id come from config, and are stored per template so different formats can pin different models
- No Anthropic SDK types may leak outside the provider module. The pipeline, evals, and tracing only see the protocol's own types
- A `FakeLLMProvider` returning fixture outputs is used in unit tests, so tests never call a paid API
- The `TranscriptionProvider` returns diarized turns, not a flat string, and follows the same pattern with a `FakeTranscriptionProvider` for tests

## Prompt Versioning

- Prompts live in code as versioned modules (`shift_note_v1.py`, `soapie_v1.py`), never edited in place. A change means a new version file
- `note_templates.prompt_version` points at the active version. Every generated note stores the `prompt_version`, provider, and model id that produced it, so any note can be traced back to exactly what generated it
- Promoting a new prompt version to active requires a passing eval run (see below). The promotion is done from `/ops/prompts` and is audit logged
- Rolling back is switching the active version back; old versions are never deleted

## LLM Evaluation Suite (backend/evals/)

This is a first-class part of the product, not an afterthought. It is also the single most persuasive artifact in the repository.

- **Golden dataset**: 30 hand-written test transcripts under `evals/datasets/`, split across both formats (15 shift notes, 15 SOAPIE). Each case is a YAML file with the transcript (as speaker turns), the exact set of flag codes that must be raised, the flag codes that must NOT be raised, and a list of facts that must appear in the note
- Cases must deliberately cover: complete notes with no flags, each individual flag code at least once, multiple missing elements at once, vague language, venting, a fall mentioned only in passing (UNREPORTED_CHANGE), a skilled intervention with no rationale (MISSING_NECESSITY_RATIONALE), **multi-speaker attribution including a family member reporting a symptom the patient does not confirm**, and transcripts containing tempting gaps where fabrication would be easy (for example vitals never mentioned)
- Thirty cases is a small sample and per-code precision/recall will have wide confidence intervals. State that honestly in `EVALS.md` rather than presenting the numbers as more certain than they are
- **Metrics per run**: flag precision and recall per flag code, overall flag F1, required-fact coverage, **fabrication check** (an automated check that every number, vital sign, time, measurement, and medication name in the output appears in the transcript, and that every patient-attributed quote appears in a turn belonging to that speaker; any unsupported value fails the case), banned phrase check, schema validity rate, average cost and latency per case
- **Runner**: `python -m evals.run --template soapie --prompt-version v2` runs the suite against the real provider, writes a JSON report to `evals/reports/`, a row to an `eval_runs` table, and **regenerates `EVALS.md` at the repo root**
- **Pass thresholds** (configurable): flag recall at least 0.95 for critical codes, overall flag F1 at least 0.90, fabrication failures exactly zero, schema validity 100%. Fabrication has zero tolerance
- **CI**: a `evals.yml` workflow runs the suite automatically on any pull request that touches `app/llm/` or `evals/`, and posts the metrics table as a PR comment. It fails the check if thresholds are not met. Deterministic unit tests for the checkers themselves (fabrication, banned phrases, flag matching, speaker attribution) run in the normal test suite with no API calls
- Keep the dataset free of real patient data; all transcripts are fictional

## LLM Observability (Langfuse)

- **Default: Langfuse Cloud free tier.** Self-hosting Langfuse is a documented optional path in `README-deploy.md`, not the default — its stack wants Postgres, ClickHouse, Redis, and object storage, which is a large amount to run beside api/worker/redis/Caddy on an Always Free VM, and an OOM there takes down the product, not just the tracing. Switching between them is an environment variable change
- Trace every pipeline run end to end: one trace per visit, with spans for download, ffmpeg, transcription, generation, repair retry if any, and flag evaluation
- Eval runs are also traced and tagged with the run id, so production behavior and eval behavior can be compared in the same tool
- Tracing is optional by config (`LANGFUSE_ENABLED`); when disabled everything works with no-op tracing

### What is actually traced when content redaction is on

Content redaction (`LANGFUSE_REDACT_CONTENT`) is **enabled by default in production** — no transcript text and no note body leaves the system. That is the correct privacy posture, but it means the trace must carry enough non-content signal to be worth having. Every trace records, explicitly:

- prompt version, provider, model id
- input tokens, output tokens, computed USD cost
- latency per span (download, ffmpeg, transcription, generation, flag evaluation)
- audio duration, speaker count detected
- the list of flag **codes** emitted and their severities (codes are not PHI)
- schema validation outcome, and whether a repair retry was needed
- transcript confidence score

That set answers the questions tracing exists to answer — is a prompt version regressing, which stage is slow, what does a note cost, how often does the model produce invalid output — without ever storing patient content. Consider Deepgram's PII redaction on the transcript as an additional layer before text reaches the LLM.

## Data Model (SQLAlchemy 2.0 + Alembic)

All timestamp columns are `TIMESTAMPTZ` storing UTC.

- **users**: email, password_hash (nullable for Google-only), google_sub, full_name, role_title (Caregiver|HHA|CNA|LPN|RN|Other), default_note_format, timezone (IANA), is_staff, **is_demo**, is_active, agency_id (nullable), agency_role (member|supervisor|owner)
- **refresh_tokens**: user_id, token_hash, family_id, expires_at, revoked_at
- **agencies** (incl. timezone), **agency_invites** (email, token, role, accepted_at, expires_at)
- **clients**: owner_id, pseudonym label only (instruct users NOT to enter full names)
- **visits**: user_id, client_id, note_format, capture_mode (live_audio|spoken_recap), visit_date, shift_start/end, **timezone**, duration_seconds, audio_key (nullable after deletion), **idempotency_key (unique per user)**, **upload_id** (R2 multipart), status (recording|uploaded|processing|ready|signed|failed)
- **consent_logs**, **transcripts** (provider, raw_text, **turns JSONB**, speaker_count, confidence)
- **notes**: format, sections JSONB, flags JSONB, **version (int, optimistic concurrency)**, edited, signed_at, signed_by, review_status (unreviewed|needs_correction|accepted), prompt_version, llm_provider, model_id
- **note_flags** *(new)*: note_id, code, severity, section_key, created_at, plus denormalized user_id and agency_id for index locality
- **note_comments**: note_id, author_id, body, resolved
- **note_templates**: format, version, section_schema JSONB, flag_schema JSONB, prompt_version, llm_provider, model_id (seed shift_note v1 AND soapie v1 in an Alembic data migration)
- **processing_jobs**: visit_id, stage, status, attempts, error_message, audio_minutes, input_tokens, output_tokens, cost_usd, latency_ms, trace_id
- **eval_runs**: template format, prompt_version, provider, model_id, metrics JSONB, passed, triggered_by (ci|manual), report_key, created_at
- **plans**, **subscriptions**, **payment_submissions**, **payment_settings** (see Billing)
- **share_links**: note_id, token, expires_at (default 30 days), revoked
- **audit_logs**: actor_id, action, entity, entity_id, metadata JSONB (view/edit/sign/export/share/delete/comment/payment approve/reject/ops actions)

### Why flags are stored twice

`notes.flags JSONB` is the note's payload — it travels with the note, matches the LLM output contract, and is what the review UI renders. It is never queried into.

`note_flags` is the analytics shape. Five dashboard views aggregate across flag codes (stacked bar by code per week, average flags per note per staff member, critical-flag rate, review queue filtered by severity, per-staff drill-down). The API contract says these are *"computed with SQL aggregation, never Python loops"* — that promise is not keepable against a JSONB array across tens of thousands of notes. Both writes happen in the same transaction as part of persisting the note; there is a test asserting they never diverge.

### Concurrency on note edits

`notes.version` increments on every section PATCH. The client sends the version it last read; a mismatch returns **409 Conflict** with the current note. Without this, an agency supervisor opening a note in the review queue while the author edits it on their phone silently discards one party's corrections — to a document that is a legal record and will be signed.

### Indexes and authorization

Every repository query is scoped to the current user; agency supervisors may READ notes of members of their own agency, never edit; staff routes require `is_staff`; demo users are rejected on every write. Tests must prove cross-tenant access fails.

Indexes on: `(user_id, status)` on visits, `(agency_id, created_at)` on notes, `(agency_id, created_at, code)` and `(note_id)` on note_flags, share link token, payment reference number, and `(user_id, idempotency_key)` unique on visits.

## API Surface (/api/v1/)

Auth (register, login, refresh, logout, Google, **demo**), profile/onboarding, agency + invites + roster, clients CRUD, visit create (idempotent) + upload credentials (single or multipart) + complete-upload + status, note retrieve / section PATCH (version-checked) / sign-off / PDF, note comments, share link create/revoke, public share retrieval, billing (plans, payment settings, subscription + entitlements, payment submissions, receipt upload URL), analytics (`/analytics/summary`, `/timeseries`, `/flags`, `/staff`, `/heatmap` — date range + staff filters, computed with SQL aggregation over `note_flags`, never Python loops), ops (`/ops/payments` list/approve/reject, `/ops/jobs` list/retry, `/ops/users` search/extend/cancel, `/ops/plans`, `/ops/payment-settings`, `/ops/prompts` list/promote, `/ops/eval-runs`, `/ops/costs`). No payment webhooks exist in this project until the Stripe phase.

## Billing (manual activation via GCash)

Payment happens out of band via GCash and the operator activates the account in the ops console. There is no card handling, no checkout SDK, and no webhooks in the MVP. Keep the entitlement layer independent of how payment happens, so another payment method can be added later without touching feature code.

### Plans (stored in the `plans` table, rendered from the API, never hardcoded)
- **Caregiver**: 25 notes/month, shift_note only
- **Nurse**: unlimited notes, both formats
- **Agency** (3 seat minimum): everything plus dashboard, review queue, analytics, staff management
- Fields: code, name, price_php, price_usd, billing_period_days, note_quota (null = unlimited), allowed_formats, features JSONB, is_active
- Every new account starts a 14-day trial automatically

### Payment flow
1. User hits a paywall and opens Upgrade
2. Upgrade shows plan selection, amount due in PHP, GCash account name and number, the GCash QR image, and instructions (all from payment_settings)
3. User pays in GCash, then submits: plan, amount, GCash reference number, date paid, sender name/number, optional receipt screenshot (uploaded via presigned URL)
4. Status `pending_review`; client shows "Payment submitted, we will activate your account shortly (usually within 24 hours)" with the reference echoed back
5. Operator approves or rejects in `/ops/payments`
6. On approval: subscription `active`, `current_period_end = max(now, existing period_end) + billing_period_days` (renewals stack, never reset), `activated_by` + note recorded, audit log, confirmation email
7. On rejection: reason shown in-app; user can resubmit

### Tables
- **subscriptions**: user_id or agency_id, plan_id, status (trialing|active|past_due|expired|cancelled), current_period_end, seats, notes_used_this_period, period_reset_at, manual, activated_by, activation_note
- **payment_submissions**: user_id, plan_id, amount, currency, method (gcash|stripe), reference_number (unique per method; duplicates rejected), paid_at, sender_name, receipt_key, status (pending_review|approved|rejected), reviewed_by, reviewed_at, rejection_reason
- **payment_settings** (single row): gcash_account_name, gcash_number, qr_image_key, instructions_markdown

### Entitlement engine (`app/services/entitlements.py`)
- One `get_entitlements(user)` returning: active, plan code, remaining quota, allowed formats, dashboard access, days remaining, grace state. Every gate in the API and both clients reads ONLY this
- FastAPI dependencies `require_active_subscription` and `require_format(format)`
- **Grace period**: 3 days past period end with a renewal banner; after grace, status `expired` and note creation blocks, while existing notes stay readable and exportable (never hold completed documentation hostage)

### Quota accounting — the rule, stated once

**Quota is consumed when a note reaches `ready`, not when a visit is created.**

A visit that fails the pipeline after 3 attempts costs the user nothing. The alternative — charging at visit creation — means a user on the 25-note Caregiver plan pays for work the system failed to deliver, which is both wrong and a support burden. Combined with the idempotency key on visit creation, a user cannot be double-charged by a network retry either.

Quota is reset at each period boundary by the daily cron.

### arq cron jobs
- Daily: expire past-grace subscriptions; renewal reminder emails (5 days, 1 day, on expiry); reset quotas for rolled-over periods; delete raw audio 24h after sign-off; email the operator if any payment submission has been pending over 24 hours

### Provider seam
`BillingProvider` protocol with a `ManualGCashProvider` in the MVP and a `StripeProvider` added in the final phase. Adding a payment method means a new provider class, with zero changes to entitlements, gates, or UI — and the Stripe phase exists specifically to demonstrate that the seam was real rather than decorative.

### Audience note (README)
GCash serves PH-based users, beta testers, and invoiced agencies; it does not serve US self-serve customers. `price_usd` and the `method` field exist so an international payment method can be added without a migration, and the Stripe phase does exactly that.

## Security, Privacy, and Compliance Posture

- Private R2 bucket; short-expiry presigned URLs minted by the API
- JWT on all routes except share retrieval (token-gated, read-only, throttled) and health
- Login throttling and temporary lockout after repeated failures; refresh token reuse detection
- Ops routes require `is_staff`, audit every action, and are additionally rate limited
- Demo users are rejected on every write path, server side
- Auto-delete raw audio 24h after sign-off; present it in the UI as a privacy feature
- Disclaimers on every note: "Drafts must be reviewed by the responsible caregiver or clinician before use. Not medical advice or a medical device." SOAPIE adds: "Final responsibility for clinical documentation accuracy rests with the signing clinician."

### Two operating modes, documented explicitly in the README

Free-tier infrastructure cannot lawfully carry PHI. Free tiers of hosting, managed Postgres, transcription, and LLM providers do not come with executed Business Associate Agreements, and a missing BAA is a HIPAA violation independent of how strong the encryption is. So the project defines two modes and never blurs them:

**Demo mode** — what is deployed publicly for the portfolio and for prospects. Free tier throughout. **Simulated and fictional audio only.** Stated plainly on the landing page and in the README.

**Pilot mode** — required before a single real visit is recorded. Paid tiers with executed BAAs from the transcription provider, the LLM provider, the object storage provider, and the database host, plus a hosting provider that will sign one. The README carries the vendor BAA checklist and the resulting monthly cost floor, so the economics of going live are visible rather than discovered later.

### A pseudonymous client label does not de-identify a recording

The `clients` table stores a pseudonym and users are instructed not to enter full names. That reduces exposure in the database; **it does not make the audio non-PHI.** The recording carries the patient's voice, their conditions, their medications, and often their address or household details. The README must say this directly rather than implying the label solves it.

### California adds obligations beyond HIPAA

If agencies in California are customers: the Confidentiality of Medical Information Act (CMIA) is stricter than HIPAA in several respects and carries a private right of action, and CCPA/CPRA applies on top. The compliance section is not HIPAA-only.

## Build Order (commit after each phase)

The web client gets capture first so that a demoable end-to-end product exists at phase 5 rather than phase 9. Mobile is still built — it moves to phase 10, where it attaches to something that already works.

| Phase | Content | Demoable |
|---|---|---|
| 1 | Monorepo scaffold: FastAPI (layered structure, config, async SQLAlchemy, Alembic, arq worker, `/healthz`), web shell (React + Vite + Router + TanStack Query + Zustand + Tailwind + shadcn/ui + Recharts), docker-compose with postgres + redis, CI workflows, OpenAPI type generation. Seed BOTH note templates via Alembic data migration | no |
| 2 | Auth: register/login/refresh rotation/logout/Google, onboarding with timezone capture; web auth store + guards + silent refresh; `create-staff-user` CLI | no |
| 3 | Capture on web: clients CRUD, idempotent visit create, presigned single + multipart upload with resume, `MediaRecorder` recording with Wake Lock, consent gate, upload progress | no |
| 4 | Pipeline: provider protocols with fake implementations first, then the arq task (ffmpeg -> diarized transcription -> template-driven generation), retries, cost recording, Langfuse tracing, status endpoint, web polling UI, `/ops/jobs` | partially |
| 5 | Review on web: section editor rendered from section_schema (no format-specific components), flags panel, version-checked PATCH, sign-off lock, WeasyPrint PDF | **yes — first honest end-to-end demo** |
| 5b | Evals: golden dataset, checkers with unit tests, runner, `eval_runs` table, `evals.yml` CI workflow with PR comments, prompt versioning with promotion gated on a passing run, generated `EVALS.md` | yes |
| 6 | Billing: plans, subscriptions, payment submissions, payment settings, entitlement engine with grace and quota-on-ready, cron jobs, Upgrade + submission screens, `/ops/payments` approve/reject with stacking period extension | yes |
| 7 | Agency dashboard (web): agencies + invites + roster, review queue with filters and comments, analytics endpoints over `note_flags` and all charts with URL-synced filters, empty/loading states, table toggle | yes |
| 8 | Share links + public share page, audio deletion, audit logging, `/ops/users`, `/ops/settings`, `/ops/prompts`, `/ops/costs`, settings screens | yes |
| 9 | Landing page; public demo login and sample share link; README, ARCHITECTURE.md, ADRs, demo video | **portfolio-complete** |
| 10 | Mobile: Expo + Expo Router, expo-audio with background and lock-screen recording, secure store, same generated API types, EAS Android internal beta | yes |
| 11 | `StripeProvider` implementing the existing `BillingProvider` protocol, with webhook handling and idempotency — changing no entitlement, gate, or UI code | yes |

## Documentation and Portfolio Packaging

The strongest engineering in this project is invisible to anyone who does not clone the repository. A reviewer gives it a few minutes. These artifacts are build items, not afterthoughts.

- **README ordering**: problem statement -> 90-second demo video -> live demo link -> architecture diagram (Mermaid) -> **AI Reliability** section -> local setup (`docker compose up`, `npm run dev`) -> deploy guide -> compliance posture. The AI Reliability section goes *above* setup instructions, because it is the differentiator and almost nobody scrolls past setup
- **AI Reliability section**: provider layer, prompt versioning, eval methodology and current scores, fabrication policy, what tracing captures under redaction
- **`EVALS.md`**: generated by the eval runner. Per-flag-code precision, recall and F1; fabrication failures; schema validity; cost and latency per note; the pass thresholds; and an honest note on the sample size
- **`ARCHITECTURE.md`** plus 6–8 short ADRs (~200 words each): arq rather than Celery; the repository layer; provider protocols for LLM and transcription; manual billing behind a provider seam; JSONB notes alongside a normalized `note_flags` table; prompt promotion gated on evals; migrations as a one-off container; web capture before native. ADRs demonstrate judgment, which is what an interviewer actually probes
- **90-second demo video** linked at the top of the README: record -> processing states -> note with flags -> fix a flag -> sign off -> PDF
- **Market positioning, stated in the README**: ambient clinical documentation is crowded at the top — Abridge, Suki, DeepScribe, Ambience, Dragon Copilot — and EHR vendors are now bundling ambient AI, some at no extra cost. This product deliberately targets what they do not: non-medical home care shift notes and small agencies with no EHR to bundle into. Saying so converts "another AI scribe" into a considered market choice
- **BAA checklist and clinical validation note**: the SOAPIE template requires licensed-nurse review before commercial launch
- **OASIS is a deliberate deferral, not an omission.** It is the single feature Medicare-certified home health agencies most want, and it is out of scope for the MVP because it is a large, separately-regulated assessment instrument. Say that explicitly with the rationale

## Quality Bar

- **Backend**: ruff + mypy strict, **pytest + pytest-asyncio + httpx AsyncClient** against a real Postgres test database (testcontainers or the compose DB), covering:
  - auth and refresh rotation, cross-tenant denial, staff-route protection, demo-user write rejection
  - entitlement engine states (trial, active, grace, expired, quota exhausted, format gated)
  - **quota consumed on `ready` and NOT consumed on `failed`**
  - **idempotent visit creation: a replayed key returns the same visit and consumes one quota unit**
  - **409 on a stale `notes.version` during section PATCH**
  - **overnight shift duration (22:00–06:00) and a shift crossing a DST transition**
  - payment approval stacking, duplicate reference rejection
  - pipeline tasks with fake transcription/LLM providers, including a multi-speaker transcript asserting no cross-speaker quote attribution
  - flag evaluation, and that `notes.flags` and `note_flags` never diverge
  - **analytics aggregation correctness against a seeded fixture with known counts — write that test first**
  - multipart upload resume after a simulated part failure
- **Web**: `tsc --noEmit` strict, **Vitest + React Testing Library** for guards, query hooks, filter-to-URL sync, chart data transforms, and the recorder state machine; **Playwright** E2E: record (stubbed `MediaRecorder`) -> upload -> processing -> review -> sign -> PDF; login -> dashboard charts render -> review queue filter -> open note -> comment; staff login -> approve a payment -> user entitlement becomes active
- **Mobile**: TypeScript strict, **Jest + React Native Testing Library** for the API client, note editor reducer, and flags panel; manual QA checklist for recording on Android
- Mobile-first for the field client; the agency dashboard is desktop-first but usable on a tablet
- Empty, loading, and error states everywhere; offline-tolerant upload with retry
- **Seed CLI** (`python -m app.cli seed-demo`): an agency with 4 staff and about 120 notes over 8 weeks with a realistic flag distribution (so every chart renders meaningfully), 3 pending payment submissions for the ops queue, plus 4 detailed sample visits (2 shift notes, 2 SOAPIE) where at least one of each triggers 3+ flags including one critical. This same data backs the public demo login
- The eval suite must pass on the active prompt versions before the MVP is considered done; zero fabrication failures
- README quality matters: this repo doubles as a portfolio piece; explain WHY each layer exists. Describe the job system as a "Redis-backed async job queue (arq)" so the concept is clear to readers who know other queue libraries

## Out of Scope (do not build)

OASIS assessments (deliberate deferral — see Documentation), EHR integrations, meeting bots, real-time transcription, note-similarity clone detection, multi-language, push notifications, offline note generation, app store submission automation, iOS distribution.
