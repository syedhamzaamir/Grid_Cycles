Grid Cycles – Tick-Level Grid Bot Backtester (Python + React)

A web app that:

Streams raw trade ticks (Polygon v3 trades) and counts grid cycles per price level.

Supports exact-only mode (arm on exact base print, close on exact base+spread print — no rounding, no crossing).

RTH filtering (09:30–16:00 ET), level band filters, CSV export.

Also supports uploading a CSV of ticks and running the same engine offline.

Contents

Requirements

Project layout

Backend (FastAPI)

Run locally

API Overview

Quick cURL tests

Frontend (Vite + React + Tailwind + Recharts)

Run locally

Build

Common issues

Render deploy (2 services)

Requirements

Python 3.11+ (3.12 recommended)

Node.js 18+ (or 20+)

npm

curl (for quick tests)

You’ll need a Polygon API key for live backtests. For CSV mode, no outside network is required.

Project layout
.
├─ backend/
│  ├─ app/
│  │  ├─ main.py            # FastAPI app, endpoints under /api/*
│  │  ├─ engine.py          # GridEngine (exact-only + crossing modes)
│  │  └─ ...                
│  └─ requirements.txt
└─ frontend/
   ├─ src/App.tsx           # UI with Polygon tab + Upload CSV tab
   ├─ vite.config.ts        # Dev proxy (if configured)
   └─ ...

Backend (FastAPI)
Run locally
# from repo root
cd backend

# create and activate venv
python -m venv .venv
source .venv/bin/activate      # (Windows: .venv\Scripts\activate)

# install deps
pip install -r requirements.txt

# set your Polygon key for live backtests (skip for CSV-only tests)
export POLYGON_API_KEY=VAt1hcpM782OIcXGvzz1zoCe3vgFrk8c 

# start API (http://localhost:8000)
uvicorn app.main:app --reload --port 8000


Open interactive docs:
http://localhost:8000/docs

API Overview

GET /api/backtest – live from Polygon
Query params:

symbol (e.g. LCID)

start_ns, end_ns (nanoseconds since epoch, UTC)

step (e.g. 0.01), spread (e.g. 0.01)

rth (true/false)

exact_only (true/false) — true = exact prints only

level_min, level_max (optional price band)

POST /api/backtest_csv – run engine on uploaded CSV (no Polygon)

multipart/form-data with:

file=@yourfile.csv

form fields symbol, step, spread, rth, exact_only, level_min, level_max (all optional except file)

CSV columns (case-insensitive):

timestamp: one of participant_timestamp_ns / participant_timestamp / timestamp_ns / time_ns / ts or iso_utc

price: price / trade_price / p

GET /api/export – (optional) CSV export of level → cycles for /api/backtest runs.

GET /api/health – simple health check.

Frontend (Vite + React + Tailwind + Recharts)
Run locally
# from repo root
cd frontend

# install deps (use `npm ci` if you have a lockfile already)
npm install

# (optional) point UI to your local API:
# create .env.development with:
# VITE_API_BASE=http://localhost:8000/api

# start dev server (http://localhost:5173)
npm run dev


Notes:

If vite.config.ts has a dev proxy for /api → http://localhost:8000, you can omit VITE_API_BASE during dev.

In production builds, the app uses VITE_API_BASE to call the backend.

Build
npm run build
npm run preview   # serves the built site for local preview

Common issues

Port already in use (8000)
Find & kill the process:

lsof -i :8000
kill -9 <PID>


npm ci fails (no lockfile)
Use npm install once to create a package-lock.json.

tsconfig.json parse error
Ensure valid JSON (no comments, trailing commas, or empty file).

CORS in browser
In dev, use Vite proxy or set VITE_API_BASE=http://localhost:8000/api.
In prod, set backend env FRONTEND_ORIGIN=https://<your-frontend>.

No data due to RTH filter
If your time window is outside 09:30–16:00 ET, set rth=false.

Render deploy (2 services)

Backend (Web Service / Python)

Build: pip install -r backend/requirements.txt

Start: uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT

Env:

POLYGON_API_KEY = your key

PYTHON_VERSION = 3.12.3

FRONTEND_ORIGIN = https://<your-frontend>.onrender.com (after frontend deployed)

Frontend (Static Site)

Root: frontend

Build: npm ci && npm run build

Publish dir: dist

Env:

VITE_API_BASE = https://<your-backend>.onrender.com/api

Open the frontend URL, pick a date (or use Upload CSV tab), and hit Run.