# Web app

Optional FastAPI + Jinja2/HTMX surface for multi-user PDF→Markdown conversion.

## Install

```bash
uv sync --extra web --group dev
```

## Environment

See `.env.example`. Important variables:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres URL (`postgresql+psycopg://...`) |
| `REDIS_URL` | Redis for RQ + SSE pub/sub |
| `WEB_DATA_DIR` | Stored PDFs + Markdown outputs |
| `WEB_DEFAULT_CREDITS` | Credits granted on signup (default 10) |
| `WEB_SECRET_KEY` | Cookie signing / app secret |
| `WEB_ALLOW_REGISTER` | Public self-serve signup (default `false`). Set `true` to enable `GET/POST /register` |
| `COOKIE_SECURE` | Mark session/CSRF cookies `Secure` (default `true`). Set `false` for local HTTP without TLS |
| `OPENCODE_API_KEY` | Server-side VLM key (never sent to clients) |
| `PDF2MD_MODEL_REGISTRY` | Optional TOML overlay for labels/pricing/`enabled` (repo `models.toml` keeps only `qwen3.7-plus` + `minimax-m3`) |
| `PDF2MD_CACHE_DIR` | Shared OCR page cache (web + worker) |
| `WEB_JOB_TIMEOUT_SECONDS` | Floor for the RQ wall-clock budget per job (default 1800) |
| `WEB_JOB_TIMEOUT_PER_PAGE_SECONDS` | Extra budget per OCR page (default 180) |
| `WEB_ETA_DEFAULT_SECONDS_PER_PAGE` | ETA seed before you have job history (default 25) |
| `WEB_ETA_PADDLE_SECONDS_PER_PAGE` | ETA seed for the local PaddleOCR backend (default 8) |
| `TEST_DATABASE_URL` | Postgres (or SQLite) for `pytest -m db` |

## Run locally

```bash
# migrate
alembic upgrade head

# API + HTML UI
pdf2md-web

# worker (separate process)
pdf2md-worker
```

Open `http://127.0.0.1:8000/` after seeding an admin and (optionally) enabling registration.

```bash
# Seed or promote an admin (idempotent). Prefer compose when using Docker:
docker compose run --rm web pdf2md-admin --email admin@example.com --password '...'
# Or locally:
pdf2md-admin --email admin@example.com --password '...'
```

Registration is off by default (`WEB_ALLOW_REGISTER=false`): signup routes return 403 (JSON) / redirect to `/login` (HTML) and marketing/login pages hide register CTAs. Admins create accounts on `/admin` (`POST /admin/users`). Self-serve registrants are always `role=user` — never promoted to admin by registration order.

Behind a reverse proxy, terminate TLS and keep `COOKIE_SECURE=true` (the default). For plain local HTTP set `COOKIE_SECURE=false`.

## Browser UI (HTMX)

After login/register you are redirected to `/documents` (HTML library).

| Page | Path | Notes |
|------|------|-------|
| Library | `GET /documents` | Upload PDF, list files, latest run status, download Markdown |
| Document | `GET /documents/{id}` | Page picker, providers, credit/time estimate, start job, recent conversions |
| Jobs | `GET /jobs` | Every conversion you started, newest first |
| Job | `GET /jobs/{id}` | Live progress, time remaining, cancel, download Markdown |
| Admin | `GET /admin` | Create users, list users, set credits (admin only) |

Shell chrome: nav (Library / Jobs / Admin), credits badge, logout. Templates live under `src/smart_pdf2md/web/templates/`.

Content negotiation: browsers send `Accept: text/html` (or `HX-Request`) and get HTML; clients that send `Accept: application/json` (or omit `text/html`) keep the JSON API responses.

### Redirects after POST

htmx issues XHR, and the browser follows a `303` transparently, so an `HX-Redirect` header set on the redirect itself never reaches htmx. `hx_redirect()` in `htmlutil.py` therefore answers HTMX requests with a bodyless `204` carrying `HX-Redirect`, and plain form posts with the usual `303`. Validation failures return `422` with an HTML fragment, and the base layout opts `422` into htmx swapping so the message is visible.

### Page selection

The document page renders one checkbox chip per page, marked `OCR` when the page has no usable text layer (same `MIN_NATIVE_CHARS` rule as `plan_ocr_pages`, so the badge never disagrees with billing). Presets cover All / Only OCR pages / Only text pages / Clear, shift-click extends a range, and a text box accepts the CLI `--page` syntax (`1-3,5`). The selection is submitted as `pages`; selecting everything sends nothing, which behaves exactly like converting the whole document.

`pages` is validated by `parse_page_selection()` and stored in `Job.options_json`, so the credit hold, the cost estimate, and `convert_full(pages=...)` all see the same subset. No migration was needed.

### Progress and time remaining

`OcrStarted.total` is the number of pages that will really hit the backend, since cache hits are filtered out first. The progress bar counts cached pages as done; the estimate counts only the remaining OCR pages:

```text
sec_per_page = EMA(alpha=0.3) over observed page durations, seeded with a prior
eta_seconds  = remaining_pages * sec_per_page - elapsed_on_current_page
```

The prior comes from the median seconds per page of your last five succeeded jobs on the same backend and model, then the same backend with any model, then `WEB_ETA_DEFAULT_SECONDS_PER_PAGE` / `WEB_ETA_PADDLE_SECONDS_PER_PAGE`. Everything is computed in `web/eta.py` from persisted `job_events` rows, so reopening a running job is accurate before SSE replays. SSE payloads carry `ts` (epoch ms) so the client can time pages across a reload.

The displayed number only jumps upward when the new estimate is more than 25 percent higher, floors at `~10s` before showing `Finishing…`, and switches to a "page N is slow" note if no event arrives for `2.5 × sec_per_page`. A queued job shows no number because queue wait is not predictable. If the estimate exceeds the worker's RQ budget (`max(WEB_JOB_TIMEOUT_SECONDS, pages × WEB_JOB_TIMEOUT_PER_PAGE_SECONDS)`) the page warns that the job may be cut short.

### Results on disk

Each job writes `WEB_DATA_DIR/{user}/{document}/jobs/{job}/output.md`, so two runs over different page subsets no longer overwrite each other. Downloads are named after the source PDF (`report.pdf` becomes `report.md`). The Library links the newest succeeded job per document.

### CSRF

On login/register the server sets:

1. HttpOnly session cookie (`smartmd_session`)
2. Non-HttpOnly `csrf` cookie — same value as `SessionRow.csrf_token`

The base layout sets `hx-headers='{"x-csrf-token": "..."}'` so HTMX POSTs send the header. `require_csrf` accepts that header (or the `csrf` cookie as fallback). You do **not** need to read CSRF from the database.

## JSON API (automation)

Same routes work as JSON for curl, OpenAPI `/docs`, and tests:

- `POST /register`, `POST /login` (form) → `303` + cookies; errors are JSON unless `Accept: text/html`
- `GET/POST /documents`, `GET /documents/{id}`
- `GET /api/providers`, `GET /api/documents/{id}/cost-estimate?pages=1-3,5`
- `POST /jobs` (accepts `pages`), `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/events` (SSE), `GET /jobs/{id}/download`, `POST /jobs/{id}/cancel`
- `GET /admin/users`, `POST /admin/users` (create user), `POST /admin/users/{id}/credits`

Example:

```bash
# after login cookies are stored in jar
curl -c jar -b jar -X POST http://127.0.0.1:8000/login \
  -d 'email=you@example.com&password=password123'

CSRF=$(grep csrf jar | awk '{print $NF}')
curl -b jar -H "x-csrf-token: $CSRF" -H "Accept: application/json" \
  http://127.0.0.1:8000/documents
```

## Docker Compose

```bash
docker compose up --build
```

Services: `web`, `worker`, `postgres:16`, `redis:7`. Shared volume for `WEB_DATA_DIR` and `PDF2MD_CACHE_DIR`. Image installs `poppler-utils`.

## Credits

1 credit = 1 OCR page actually processed (`PageDone` events). Native text and cache hits are free. On submit the API holds `ocr_pages - cached` for the selected pages only; the worker may top up one credit at a time if cache disappeared; settle refunds unused hold. Cancelling a job that never left the queue settles it immediately, since no worker will run to release the hold. Admin can set balances via the Admin UI or `POST /admin/users/{id}/credits`.

## Auth

Email/password, Argon2 hashes, server-side session cookies (`Secure` by default), CSRF via `x-csrf-token` / `csrf` cookie. Seed the first admin with `pdf2md-admin` (or `docker compose run --rm web pdf2md-admin ...`). Self-serve registration, when enabled, always creates `role=user`. Admins create users (always `role=user`, default credits) via `POST /admin/users` without switching session.
