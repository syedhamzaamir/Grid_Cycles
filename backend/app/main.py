from __future__ import annotations
import os
import asyncio
import datetime as dt
from decimal import Decimal
from typing import AsyncGenerator, Dict, Optional
from pathlib import Path
from fastapi.staticfiles import StaticFiles
import httpx
import pytz
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .engine import GridEngine
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI(title="Grid Cycle Backtester")

# Allow the frontend origin (during bring-up we allow all, then tighten later)
frontend_origin = os.getenv("FRONTEND_ORIGIN", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin] if frontend_origin != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

POLY_KEY = os.getenv("POLYGON_API_KEY")
POLY_BASE = "https://api.polygon.io"
NY = pytz.timezone("America/New_York")

app = FastAPI(title="Grid Cycle Backtester", root_path="")

# CORS for local dev; in Docker we serve SPA from the same origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class CycleResult(BaseModel):
    symbol: str
    step: str
    spread: str
    start_iso: str
    end_iso: str
    rth: bool
    totals: Dict[str, int]
    top_levels: list
    samples: int

def in_rth(ns: int) -> bool:
    # convert ns to ET and test 09:30–16:00
    ts = dt.datetime.utcfromtimestamp(ns / 1_000_000_000).replace(tzinfo=dt.timezone.utc).astimezone(NY)
    t = ts.time()
    return dt.time(9, 30) <= t <= dt.time(16, 0)

async def fetch_trades(symbol: str, start_ns: int, end_ns: int) -> AsyncGenerator[dict, None]:
    """
    Stream trades ascending by participant_timestamp with pagination.
    Uses timestamp.gte/lt filters, order asc, sort=participant_timestamp.
    Retries on 429 with exponential backoff and jitter.
    """
    if not POLY_KEY:
        raise HTTPException(500, "Server missing POLYGON_API_KEY")
    url = f"{POLY_BASE}/v3/trades/{symbol}"
    params = {
        "timestamp.gte": str(start_ns),
        "timestamp.lt": str(end_ns),
        "order": "asc",
        "sort": "participant_timestamp",
        "limit": 50000,
        "apiKey": POLY_KEY,
    }
    backoff = 1.0
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            r = await client.get(url, params=params)
            if r.status_code == 429:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8.0)
                continue
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise HTTPException(e.response.status_code, e.response.text)
            data = r.json()
            for row in data.get("results", []):
                yield row
            next_url = data.get("next_url")
            if not next_url:
                break
            # next_url already has cursor and filters; only pass key
            url = next_url
            params = {"apiKey": POLY_KEY}
            backoff = 1.0

@app.get("/api/health", include_in_schema=False)
def health():
    return {"ok": True}


@app.get("/api/backtest", response_model=CycleResult)
async def backtest(
    symbol: str = Query(..., description="Ticker, e.g., LCID"),
    start_ns: int = Query(..., description="Start (ns since epoch, UTC)"),
    end_ns: int = Query(..., description="End (ns since epoch, UTC)"),
    step: str = Query("0.01"),
    spread: str = Query("0.01"),
    rth: bool = Query(True),
    exclude_trf: bool = Query(False, description="Exclude TRF prints"),
    max_correction: Optional[int] = Query(None, description="Keep trades where correction <= this number"),
    exact_only: bool = Query(False, description="Require exact prints at base and base+spread (no crossing)"),
    level_min: Optional[str] = Query(None, description="Only count cycles for base levels >= this price"),
    level_max: Optional[str] = Query(None, description="Only count cycles for base levels <= this price"),
):
    # inputs
    try:
        step_d = Decimal(step)
        spread_d = Decimal(spread)
        level_min_d = Decimal(level_min) if level_min is not None and level_min != "" else None
        level_max_d = Decimal(level_max) if level_max is not None and level_max != "" else None
    except Exception:
        raise HTTPException(400, "step/spread/level_min/level_max must be valid decimals")
    if start_ns >= end_ns:
        raise HTTPException(400, "start_ns must be < end_ns")

    # engine
    try:
        engine = GridEngine(
            step_d, spread_d,
            exact_only=exact_only,
            level_min=level_min_d, level_max=level_max_d
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    # stream ticks
    async for tr in fetch_trades(symbol, start_ns, end_ns):
        ns = tr.get("participant_timestamp") or tr.get("sip_timestamp")
        if ns is None:
            continue

        if exclude_trf and tr.get("trf_timestamp") is not None:
            continue
        if max_correction is not None and tr.get("correction") is not None:
            try:
                if int(tr["correction"]) > max_correction:
                    continue
            except Exception:
                pass

        if rth and not in_rth(int(ns)):
            continue

        price = Decimal(str(tr["price"]))
        engine.feed(price, int(ns))

    out = engine.finalize()
    return CycleResult(
        symbol=symbol,
        step=str(step_d),
        spread=str(spread_d),
        start_iso=dt.datetime.utcfromtimestamp(start_ns / 1e9).isoformat() + "Z",
        end_iso=dt.datetime.utcfromtimestamp(end_ns / 1e9).isoformat() + "Z",
        rth=rth,
        totals=out["totals"],
        top_levels=out["top_levels"],
        samples=out["samples"],
    )

@app.get("/api/export", response_class=PlainTextResponse)
async def export_csv(
    symbol: str,
    start_ns: int,
    end_ns: int,
    step: str = "0.01",
    spread: str = "0.01",
    rth: bool = True,
):
    # simple reuse by calling the backtest handler and formatting CSV
    result: CycleResult = await backtest(symbol, start_ns, end_ns, step, spread, rth)  # type: ignore
    lines = ["level,cycles"]
    for level, cnt in result.totals.items():
        lines.append(f"{level},{cnt}")
    return "\n".join(lines)

# Serve the built SPA (copied into /app/static in Docker)
STATIC_DIR = (Path(__file__).parent / "static").resolve()

if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:
    @app.get("/", include_in_schema=False)
    def home():
        return {
            "ok": True,
            "message": "Frontend not built. Run the UI in dev with Vite or build and copy to backend/app/static."
        }