
# SignalDesk

SignalDesk turns a scraped lead list into a ranked, verified acquisition pipeline. It is a five-hour-scope companion to SaaSquatch for search-fund entrepreneurs, acquisition operators, and focused outbound teams.

## What is included

- Explainable buy-box scoring with 0-100 scores, A-D tiers, tunable weights, and reason chips.
- Multi-source pipeline for SaaSquatch-style CSV files, OpenStreetMap discovery, and public website enrichment.
- Normalization, fuzzy-friendly deduplication, validation flags, confidence scoring, and an audit trail.
- Demo data with no login, filters, virtualized table rendering, CRM-ready CSV export, deterministic outreach drafts, and a Data & Ethics page.

This repository contains synthetic sample data only. It does not harvest private personal data and does not bypass CAPTCHAs, robots.txt, rate limits, or access controls.

## Stack

- Frontend: React 18, Vite, TypeScript strict mode, Tailwind CSS, shadcn-style local UI primitives, TanStack Query, TanStack Table, TanStack Virtual, React Router.
- Backend: Python 3.12+, FastAPI, Pydantic v2, httpx, pytest, ruff, mypy.
- Database: Supabase Postgres. The app falls back to demo data when Supabase variables are not configured.
- Hosting: Vercel static frontend plus a Vercel Python serverless function at `api/index.py`.

## Local setup

### Prerequisites

- Node.js 20+
- Python 3.12+
- A Supabase project is optional for the demo and required for persistence.

### Backend

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env
uvicorn api.app.main:app --reload --port 8000
```

API docs are available at `http://localhost:8000/api/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

For local frontend-to-backend requests, set `VITE_API_URL=http://127.0.0.1:8000` in `frontend/.env`, or use the frontend fallback demo data.

### Supabase

1. Create a Supabase project in a US region close to the intended users. Record the actual region in `docs/ARCHITECTURE.md` after creation.
2. Open Supabase SQL Editor.
3. Paste and run `supabase/schema.sql`.
4. Put the project URL and service-role key in the backend environment only. Never expose the service-role key through Vite.

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=replace-me
```

### Tests and quality checks

```bash
pytest
ruff check api
mypy api
python scripts/benchmark.py --rows 10000
```

Frontend checks:

```bash
cd frontend
npm run lint
npm run build
```

No packages are installed by this repository. Install them yourself from the manifests above.

## Vercel and Render deployment

1. Deploy the backend as a Render Web Service with start command `uvicorn api.app.main:app --host 0.0.0.0 --port $PORT`.
2. Set Render `FRONTEND_ORIGIN` to the Vercel origin, for example `https://signaldeskpy.vercel.app`.
3. Import the repository into Vercel with `frontend` as the root directory, build command `npm run build`, and output directory `dist`.
4. Set the Vercel environment variable `VITE_API_URL` to the complete Render URL, for example `https://your-service.onrender.com`.
5. Redeploy Vercel after saving the environment variable because Vite embeds it during the build.
6. Confirm the Render endpoints `/api/health` and `/api/pipeline/demo`, then test the frontend demo and outreach flows.

## Reference analysis

SaaSquatch publicly presents company/person discovery, industry and location filtering, enrichment, revenue estimates, AI company scoring, save/export workflows, analytics, and outreach modules. SignalDesk focuses on the next decision after discovery: which lead should be contacted first, and what data can be trusted?

## Benchmark

Run the benchmark locally after installing the requirements:

```bash
python scripts/benchmark.py --rows 10000
```

The script prints measured timings for normalization, deduplication, validation, and scoring. Results are intentionally not fabricated here; record the output from your machine in your submission video or README after running it.

## Limitations and roadmap

- Public-source discovery depends on third-party availability and may return partial results.
- MX validation is optional and disabled by default unless configured.
- Supabase persistence is intentionally backend-only; the demo remains useful without an account.
- Future work: authenticated workspaces, background jobs, CRM OAuth integrations, richer website extraction, and source-specific quality calibration.

## Submission files

- `docs/ARCHITECTURE.md` - UX, architecture, data, cache, hosting, and deployment decisions.
- `docs/BUILD_LOG.md` - planned five-hour build plan; edit with actual time.
- `VIDEO_SCRIPT.md` - 1:45-2:00 recording script and shot list.
- `BUSINESS_UNDERSTANDING.md` - draft answers with personal placeholders and `[VERIFY]` markers.
- `EMAIL_DRAFT.md` - editable submission email.
- `api_demo.py` - API walkthrough.
- `supabase/schema.sql` - paste into Supabase SQL Editor.

## License

MIT for the implementation. OpenStreetMap data, when used, remains subject to the Open Database License (ODbL). The bundled dataset is synthetic.

## Links to complete before submission

- Live demo: [replace with deployed URL]
- Video walkthrough: [replace with video URL]
- Screenshots/GIF: add the final capture under `docs/screenshots/` and link it here.

## Self-audit

See `docs/SELF_AUDIT.md` for the rubric score table and remaining user-owned tasks.
