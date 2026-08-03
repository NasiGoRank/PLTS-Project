# PLTS monitoring backend for Render

This FastAPI service runs the existing Huawei/Kehua scraper, normalizes the responses, and stores the result in Supabase.

## Storage model

After each scrape:

1. The newest normalized payload is upserted into `monitoring_current`.
2. A historical row is inserted into `monitoring_snapshots` when the history interval is due.
3. History older than the configured retention period is deleted.

The local `/tmp` output is only temporary diagnostic output. Supabase is the durable source used by API responses.

## Required setup

Run `../supabase/schema.sql` in the Supabase SQL Editor before starting this service.

Required Render secrets:

```text
SUPABASE_URL
SUPABASE_SECRET_KEY
FRONTEND_ORIGIN
HUAWEI_USERNAME
HUAWEI_PASSWORD
KEHUA_USERNAME
KEHUA_PASSWORD
HUAWEI_COOKIES_JSON
REFRESH_SECRET
```

`SUPABASE_SECRET_KEY` may contain a current Supabase secret key or the legacy `service_role` key. It must remain server-side.
Publishable (`sb_publishable_...`) and legacy `anon` keys are rejected because
they cannot write to the private monitoring tables.

## Render deployment

For a monorepo, use the root `render.yaml`. For a backend-only repository, use this directory's `render.yaml`.

Render commands are already configured:

```text
Build: pip install -r requirements.txt
Start: uvicorn api:app --host 0.0.0.0 --port $PORT
Health check: /health
```

## Endpoints

- `GET /health`: process liveness, scraper state, and safe database configuration status.
- `GET /ready`: confirms a current row exists in Supabase.
- `GET /api/status`: latest scraper/database metadata.
- `GET /api/current`: newest normalized dashboard payload from Supabase.
- `GET /api/history`: historical snapshot metadata, optionally including payloads.

Captured Huawei and Kehua blueprints are request templates only. Immediately
before replay, the scraper replaces their chart dates with the current
Asia/Jakarta day, month, or year. Huawei's matching epoch timestamp and Kehua's
payload signature are regenerated at the same time.
- `POST /api/refresh`: runs one authenticated scrape for an external scheduler.

For the deployed free web service, set `AUTO_SCRAPE=false` and schedule a POST
request every 10 minutes with this header:

```text
Authorization: Bearer YOUR_REFRESH_SECRET
```

The request can take 15–60 seconds because it waits for both upstream platforms
and the Supabase write to finish. HTTP 409 means another refresh is still active.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

The service loads this local `.env` automatically and supports multiline JSON
cookie exports. Runtime environment variables supplied by Render take precedence.

Kehua cookies are optional when `KEHUA_USERNAME` and `KEHUA_PASSWORD` are set.
Before each scrape the backend validates the current authorization token. If it
has expired, the backend reproduces Kehua's signed login request and uses the new
token only in server memory for that scrape. Credentials and tokens are excluded
from API responses and authentication summaries.

Liveness-only smoke test:

```bash
AUTO_SCRAPE=false uvicorn api:app --host 127.0.0.1 --port 8000
```
