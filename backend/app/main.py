from __future__ import annotations

import os
import io
import csv
import asyncio
import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional

import httpx
import pytz
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .engine import GridEngine

# -----------------------------------------------------------------------------
# App & Config
# -----------------------------------------------------------------------------
app = FastAPI(title="Grid Cycle Backtester", root_path="")

# CORS (during bring-up we allow all; set FRONTEND_ORIGIN to tighten)
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

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def in_rth(ns: int) -> bool:
    """RTH: 09:30–16:00 America/New_York (DST-aware)."""
    ts = (
        dt.datetime.utcfromtimestamp(ns / 1_000_000_000)
        .replace(tzinfo=dt.timezone.utc)
        .astimezone(NY)
    )
    t = ts.time()
    return dt.time(9, 30) <= t <= dt.time(16, 0)


def _parse_hms(s: str) -> dt.time:
    """
    Parse "HH:MM" or "HH:MM:SS" (24h). Raises HTTP 400 on bad input.
    """
    try:
        if len(s.split(":")) == 2:
            return dt.time.fromisoformat(s + ":00")
        return dt.time.fromisoformat(s)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid time '{s}', expected HH:MM or HH:MM:SS")


def dates_times_to_ns(
    start_date: str,
    end_date: str,
    tzname: str = "America/New_York",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> tuple[int, int]:
    """
    Convert local dates/times in `tzname` to a UTC nanosecond window.

    If start_time/end_time are omitted:
      window = [start_date 00:00 local, (end_date + 1 day) 00:00 local)
    If times are provided:
      window = [start_date start_time, end_date end_time)

    Enforces start < end.
    """
    try:
        tz = pytz.timezone(tzname)

        # dates
        s_day = dt.datetime.strptime(start_date, "%Y-%m-%d").date()
        e_day = dt.datetime.strptime(end_date, "%Y-%m-%d").date()

        # times
        s_time = _parse_hms(start_time) if start_time else dt.time(0, 0, 0)
        if end_time:
            e_time = _parse_hms(end_time)
            e_daytime = dt.datetime.combine(e_day, e_time)
        else:
            # default: exclusive next midnight after end_date
            e_daytime = dt.datetime.combine(e_day, dt.time(0, 0, 0)) + dt.timedelta(days=1)

        s_local = tz.localize(dt.datetime.combine(s_day, s_time))
        e_local = tz.localize(e_daytime)

        s_utc = s_local.astimezone(dt.timezone.utc)
        e_utc = e_local.astimezone(dt.timezone.utc)

        s_ns = int(s_utc.timestamp() * 1_000_000_000)
        e_ns = int(e_utc.timestamp() * 1_000_000_000)
        if s_ns >= e_ns:
            raise HTTPException(status_code=400, detail="start must be before end")
        return s_ns, e_ns
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid date/time(s): {e}")

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

# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/api/health", include_in_schema=False)
def health():
    return {"ok": True}

@app.get("/api/backtest", response_model=CycleResult)
async def backtest(
    symbol: str = Query(..., description="Ticker, e.g., LCID"),

    # Either provide ns window...
    start_ns: Optional[int] = Query(None, description="Start (ns since epoch, UTC)"),
    end_ns: Optional[int] = Query(None, description="End (ns since epoch, UTC)"),

    # ...or calendar dates/times in a given tz (default ET)
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD) in the given tz"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD) in the given tz"),
    start_time: Optional[str] = Query(None, description="Optional start time HH:MM or HH:MM:SS in the given tz"),
    end_time: Optional[str] = Query(None, description="Optional end time HH:MM or HH:MM:SS in the given tz"),
    tz: str = Query("America/New_York", description="IANA timezone for date/time inputs (default ET)"),

    step: str = Query("0.01"),
    spread: str = Query("0.01"),
    rth: bool = Query(True),
    exclude_trf: bool = Query(False, description="Exclude TRF prints"),
    max_correction: Optional[int] = Query(None, description="Keep trades where correction <= this number"),
    exact_only: bool = Query(False, description="Require exact prints at base and base+spread (no crossing)"),
    level_min: Optional[str] = Query(None, description="Only count cycles for base levels >= this price"),
    level_max: Optional[str] = Query(None, description="Only count cycles for base levels <= this price"),
):
    # Resolve time window
    if start_date and end_date:
        start_ns_eff, end_ns_eff = dates_times_to_ns(start_date, end_date, tz, start_time, end_time)
    elif start_ns is not None and end_ns is not None:
        start_ns_eff, end_ns_eff = int(start_ns), int(end_ns)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either (start_ns & end_ns) or (start_date & end_date).",
        )
    if start_ns_eff >= end_ns_eff:
        raise HTTPException(status_code=400, detail="start must be < end")

    # Numeric inputs
    try:
        step_d = Decimal(step)
        spread_d = Decimal(spread)
        level_min_d = Decimal(level_min) if level_min not in (None, "") else None
        level_max_d = Decimal(level_max) if level_max not in (None, "") else None
    except Exception:
        raise HTTPException(status_code=400, detail="step/spread/level_min/level_max must be valid decimals")

    # Engine
    try:
        engine = GridEngine(
            step_d,
            spread_d,
            exact_only=exact_only,
            level_min=level_min_d,
            level_max=level_max_d,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Stream ticks
    async for tr in fetch_trades(symbol, start_ns_eff, end_ns_eff):
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
        start_iso=dt.datetime.utcfromtimestamp(start_ns_eff / 1e9).isoformat() + "Z",
        end_iso=dt.datetime.utcfromtimestamp(end_ns_eff / 1e9).isoformat() + "Z",
        rth=rth,
        totals=out["totals"],
        top_levels=out["top_levels"],
        samples=out["samples"],
    )

@app.get("/api/export", response_class=PlainTextResponse)
async def export_csv(
    symbol: str,
    # support either ns or dates just like /api/backtest
    start_ns: Optional[int] = None,
    end_ns: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    tz: str = "America/New_York",
    step: str = "0.01",
    spread: str = "0.01",
    rth: bool = True,
    exact_only: bool = False,
    level_min: Optional[str] = None,
    level_max: Optional[str] = None,
):
    result: CycleResult = await backtest(  # type: ignore
        symbol=symbol,
        start_ns=start_ns,
        end_ns=end_ns,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        tz=tz,
        step=step,
        spread=spread,
        rth=rth,
        exact_only=exact_only,
        level_min=level_min,
        level_max=level_max,
    )
    lines = ["level,cycles"]
    for level, cnt in result.totals.items():
        lines.append(f"{level},{cnt}")
    return "\n".join(lines)

# -----------------------------------------------------------------------------
# CSV upload -> run engine offline
# -----------------------------------------------------------------------------
@app.post("/api/backtest_csv", response_model=CycleResult)
async def backtest_csv(
    file: UploadFile = File(..., description="CSV with at least timestamp+price columns"),
    symbol: str = Form("TEST"),
    step: str = Form("0.01"),
    spread: str = Form("0.01"),
    rth: bool = Form(False),
    exact_only: bool = Form(True),
    level_min: Optional[str] = Form(None),
    level_max: Optional[str] = Form(None),
):
    """
    Run the grid engine on an uploaded CSV (no Polygon calls).
    Expected columns (case-insensitive, flexible):
      - timestamp ns: one of participant_timestamp_ns, participant_timestamp, timestamp_ns, time_ns, ts
      - or ISO time: iso_utc (as a fallback; will convert to ns)
      - price: price / trade_price / p
    """
    step_d = Decimal(step)
    spread_d = Decimal(spread)
    lvl_min_d = Decimal(level_min) if level_min else None
    lvl_max_d = Decimal(level_max) if level_max else None

    # Load CSV into memory (text) and sniff columns
    raw = await file.read()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace")))
    rows = list(reader)

    if not rows:
        raise HTTPException(400, "CSV appears empty")

    # Resolve column names (case-insensitive)
    def pick(cols, *candidates):
        lower = {c.lower(): c for c in cols}
        for cand in candidates:
            if cand in lower:
                return lower[cand]
        # fuzzy contains match
        for c in cols:
            lc = c.lower()
            if any(cand in lc for cand in candidates):
                return c
        return None

    cols = rows[0].keys()
    ts_col = pick(
        cols,
        "participant_timestamp_ns",
        "participant_timestamp",
        "timestamp_ns",
        "time_ns",
        "ts",
    )
    iso_col = pick(cols, "iso_utc", "iso", "time", "timestamp")
    price_col = pick(cols, "price", "trade_price", "p")

    if not price_col:
        raise HTTPException(400, f"Couldn't find a price column in {list(cols)}")

    def to_ns(row) -> Optional[int]:
        if ts_col and row.get(ts_col):
            try:
                return int(row[ts_col])
            except Exception:
                pass
        if iso_col and row.get(iso_col):
            try:
                dtobj = dt.datetime.fromisoformat(row[iso_col].replace("Z", "")).replace(tzinfo=dt.timezone.utc)
                return int(dtobj.timestamp() * 1_000_000_000)
            except Exception:
                pass
        return None

    # Sort rows by ns (ascending), discard invalid
    material = []
    for r in rows:
        ns = to_ns(r)
        if ns is None:
            continue
        try:
            price = Decimal(str(r[price_col]))
        except Exception:
            continue
        material.append((ns, price))
    material.sort(key=lambda x: x[0])

    if not material:
        raise HTTPException(400, "No usable rows (timestamp/price) found in CSV")

    # Run engine
    engine = GridEngine(
        step_d,
        spread_d,
        exact_only=exact_only,
        level_min=lvl_min_d,
        level_max=lvl_max_d,
    )

    first_ns = material[0][0]
    last_ns = material[-1][0]

    for ns, price in material:
        if rth and not in_rth(ns):
            continue
        engine.feed(price, ns)

    out = engine.finalize()
    return CycleResult(
        symbol=symbol,
        step=str(step_d),
        spread=str(spread_d),
        start_iso=dt.datetime.utcfromtimestamp(first_ns / 1e9).isoformat() + "Z",
        end_iso=dt.datetime.utcfromtimestamp(last_ns / 1e9).isoformat() + "Z",
        rth=rth,
        totals=out["totals"],
        top_levels=out["top_levels"],
        samples=out["samples"],
    )

# -----------------------------------------------------------------------------
# Static files (built SPA copied into backend/app/static in Docker)
# -----------------------------------------------------------------------------
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
