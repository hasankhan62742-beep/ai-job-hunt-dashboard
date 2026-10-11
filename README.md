# AI Job Hunt Dashboard — real jobs, honest AI

A killer dashboard with a strict honesty contract:

- **Job listings are REAL** — pulled live from free public employer-board APIs.
  The AI never invents jobs, companies, salaries, or apply links.
- **The AI only analyzes YOUR CV** — profile strengths, skill gaps, 30-day roadmap.
- Every listing carries an **evidence-based verification badge**
  (`✓ Official`, `Board listing`, `? Unconfirmed`…) — never overstated.

## Free real APIs used (no key needed)

| Source | What it is | Docs |
|---|---|---|
| Greenhouse public Job Board API | Employer career boards (e.g. Airbnb, Appier, Glean) | https://developers.greenhouse.io/job-board.html |
| Lever public Postings API | Employer career boards (US + EU endpoints) | https://github.com/lever/postings-api |
| RemoteOK public API | Remote-only job board (attribution required) | https://remoteok.com/api |

Add more boards in `backend/config.yaml` (any `boards.greenhouse.io/{slug}`
or `jobs.lever.co/{Slug}`).

## Paid (optional): CV analysis

`POST /api/analyze` uses the Anthropic Messages API with **your** key, kept
**server-side only** in `backend/.env` — the browser never sees it and never
calls Anthropic directly. Without a key, CV analysis is cleanly disabled and
job listings keep working.

## Run locally

```bash
# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # add ANTHROPIC_API_KEY for CV analysis (optional)
# backend/config.yaml already includes verified boards; add more slugs as needed
JOBHUNT_DB_PATH=$PWD/data/jobhunt.db .venv/bin/uvicorn app:app --port 8000

# frontend (new terminal)
cd frontend
npm install
npm run dev   # http://localhost:5173  (proxies /api -> :8000)
```

## Deploy

- **Frontend:** Vercel / Netlify / Cloudflare Pages — `npm run build`, serve `dist/`.
  Set the API base URL if the backend isn't same-origin (edit `src/api.js` `BASE`).
- **Backend:** Render / Railway / any VPS —
  `uvicorn app:app --host 0.0.0.0 --port $PORT`, env vars `ANTHROPIC_API_KEY`,
  `JOBHUNT_DB_PATH` (use a persistent disk for the SQLite DB).
- **CORS:** add your frontend origin to `allow_origins` in `backend/app.py`.

## Push to GitHub (fresh repo)

```bash
cd ai-job-hunt-dashboard
git init -b main
git add .
git commit -m "AI Job Hunt Dashboard: real verified jobs + honest CV analysis"
# create an empty repo on github.com (web UI), then:
git remote add origin https://github.com/<your-username>/ai-job-hunt-dashboard.git
git push -u origin main
```

Never commit `backend/.env` (it's gitignored).
