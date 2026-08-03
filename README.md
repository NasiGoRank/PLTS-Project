# PLTS monitoring deployment bundle

Production-shaped deployment for:

```text
Huawei + Kehua APIs
        ↓
Render: FastAPI scraper/backend
        ↓
Supabase: current snapshot + retained history
        ↓
Vercel: Vite/React dashboard
```

## Repository layout

```text
backend/     FastAPI, scraper, Render configuration
frontend/    Vite/React dashboard, Vercel configuration
supabase/    SQL schema and database setup notes
render.yaml  Render Blueprint for the monorepo
```

No login credentials, live cookies, raw HAR files, browser profiles, generated scrape output, `node_modules`, or frontend build output are included.

## Deployment order

### 1. Create the Supabase database

1. Create a Supabase project.
2. Open **SQL Editor**.
3. Run [`supabase/schema.sql`](supabase/schema.sql).
4. Copy the project URL and a server-side secret key.

The frontend does not connect to Supabase directly. Only Render receives the Supabase secret key.

### 2. Deploy the backend on Render

Push this folder to a private GitHub repository, then create a Render **Blueprint** from it. The root `render.yaml` selects `backend/` automatically.

Set these Render secret variables:

```text
SUPABASE_URL
SUPABASE_SECRET_KEY
FRONTEND_ORIGIN=*
HUAWEI_USERNAME
HUAWEI_PASSWORD
KEHUA_USERNAME
KEHUA_PASSWORD
KEHUA_ACCOUNTS_JSON
HUAWEI_COOKIES_JSON
REFRESH_SECRET
```

For `HUAWEI_COOKIES_JSON`, paste the complete JSON cookie export. Do not wrap
the whole JSON in an additional pair of quotes. Kehua can log in automatically
with `KEHUA_USERNAME` and `KEHUA_PASSWORD`, so `KEHUA_COOKIES_JSON` is optional.
Additional Kehua logins use `KEHUA_ACCOUNTS_JSON`. Each entry includes credentials
and the non-secret identifiers used to rewrite the captured request template:

```json
[{
  "name": "school-09",
  "username": "replace-me",
  "password": "replace-me",
  "company_id": "1831",
  "station_id": "17483",
  "area_code": "2054",
  "company_name": "SDN 09 JAKUT"
}]
```

The original `KEHUA_USERNAME`/`KEHUA_PASSWORD` account remains supported. Each
account receives an isolated session, and their stations are merged into one
Kehua fleet in the normalized API response.

The non-secret defaults are already declared in `render.yaml`:

```text
SCRAPE_INTERVAL_SECONDS=300
HISTORY_INTERVAL_SECONDS=3600
HISTORY_RETENTION_DAYS=30
```

Check the deployed backend in this order:

```text
https://YOUR-RENDER-SERVICE.onrender.com/health
https://YOUR-RENDER-SERVICE.onrender.com/ready
https://YOUR-RENDER-SERVICE.onrender.com/api/status
https://YOUR-RENDER-SERVICE.onrender.com/api/current
```

`/ready` returns HTTP 503 until the first successful scrape is stored in Supabase.

### 3. Deploy the frontend on Vercel

Import the same GitHub repository into Vercel and set:

```text
Root Directory: frontend
Framework: Vite
Build Command: npm run build
Output Directory: dist
```

Add:

```text
VITE_API_URL=https://YOUR-RENDER-SERVICE.onrender.com
VITE_POLL_INTERVAL_MS=60000
```

Deploy, copy the final Vercel origin, then replace Render's temporary CORS value:

```text
FRONTEND_ORIGIN=https://YOUR-VERCEL-PROJECT.vercel.app
```

Redeploy the Render backend after changing the origin.

## Database behavior

The backend writes normalized monitoring data, not raw authenticated HTTP responses.

- `monitoring_current`: one row, updated after every scrape.
- `monitoring_snapshots`: historical rows saved at the configured history interval.
- Old history rows are deleted according to `HISTORY_RETENTION_DAYS`.

API endpoints:

```text
GET /health
GET /ready
GET /api/status
GET /api/current
GET /api/history?limit=24
GET /api/history?limit=24&include_payload=true
```

Each successful refresh also upserts one row per station and local calendar day
into `monitoring_site_daily`. Apply
`supabase/migrations/20260803000000_site_daily_rollups.sql` before deploying this
version. These durable facts are the source for comparable long-term site energy
and revenue charts; raw hourly snapshots can continue using their normal
retention window.

History responses are capped at 168 rows per request.

For the free Render deployment, an external scheduler calls `POST /api/refresh`
every 10 minutes with `Authorization: Bearer <REFRESH_SECRET>`. Render runs with
`AUTO_SCRAPE=false`, so each scheduled request produces exactly one scrape while
also keeping the web service inside Render's idle window.

## Local development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

The backend loads `backend/.env` automatically for local development. Cookie
JSON may be formatted on one line or across multiple lines. Existing process
environment variables always take precedence over values in the file.

For a liveness-only smoke test without scraping or Supabase access:

```bash
AUTO_SCRAPE=false uvicorn api:app --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

## Security

- Keep the repository private.
- Rotate any password or session token that was previously uploaded or committed.
- Never put `SUPABASE_SECRET_KEY`, cookies, or passwords in Vercel.
- Never use secrets in variables prefixed with `VITE_`; those values are shipped to browsers.
- Store all Kehua credentials, including `KEHUA_ACCOUNTS_JSON`, only on the backend. The backend refreshes each account's authorization automatically when its token expires.
