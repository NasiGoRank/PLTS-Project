# Repository Guidelines

## Project Structure & Module Organization

This repository is a deployment bundle for PLTS monitoring.

- `backend/`: FastAPI service, scraper logic, Supabase storage adapter, cookie/env loading, and Python unit tests.
- `frontend/`: Vite React dashboard deployed to Vercel.
- `supabase/`: SQL schema and migrations for `monitoring_current` and `monitoring_snapshots`.
- `render.yaml`: Render backend deployment configuration.
- Root Markdown files document deployment, authentication, and operational behavior.

Keep generated outputs, cookies, browser exports, `.env` files, `node_modules/`, and frontend `dist/` out of version control.

## Build, Test, and Development Commands

Backend local setup:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

Backend tests:

```bash
cd backend
python -m unittest test_env_loader.py test_refresh.py test_kehua_auth.py test_supabase_store.py test_site_rollups.py test_dynamic_request_dates.py test_huawei_energy_charts.py
python -m py_compile api.py scrape_monitoring.py supabase_store.py
```

Frontend commands:

```bash
cd frontend
npm install
npm run dev
npm run build
npm run preview
```

## Coding Style & Naming Conventions

Use Python 3.12-compatible code in `backend/`, with 4-space indentation and snake_case names. Keep scraper helpers focused and avoid logging raw cookies, tokens, passwords, or Supabase secret keys.

Use React/Vite conventions in `frontend/`: component files should be clear, named by purpose, and keep browser-exposed config limited to `VITE_` variables. Do not place backend secrets in frontend env files.

## Testing Guidelines

Python tests use `unittest` and live beside backend modules as `test_*.py`. Add or update tests for scraper auth behavior, API refresh behavior, env parsing, and Supabase storage changes. Prefer safe fixtures and mocks; never embed real credentials or live tokens in tests.

Run the backend unit tests before pushing backend changes and `npm run build` before pushing frontend changes.

## Commit & Pull Request Guidelines

History uses concise conventional-style commits such as `fix: renew Kehua authorization automatically` and `docs: explain Kehua automatic auth refresh`. Use `feat:`, `fix:`, `docs:`, `test:`, `chore:`, or `refactor:` and keep each commit scoped to one logical change.

Pull requests should describe what changed, why it changed, validation performed, and any deployment or environment-variable impact. Include screenshots only for visible frontend changes.

## Security & Configuration Tips

Store secrets only in `backend/.env`, Render environment variables, or Supabase/Vercel dashboards as appropriate. Rotate any token or password exposed in logs, shell history, or committed files. `/api/refresh` must remain protected by `REFRESH_SECRET`.
