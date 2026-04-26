from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .database import (
    fetch_companies,
    fetch_symbol_data,
    fetch_symbol_history,
    init_db,
)
from .services import (
    COMPANY_MASTER,
    DataSourceUnavailableError,
    bootstrap_companies,
    prediction_points,
    refresh_symbol,
    sentiment_index,
    volatility_score,
)

app = FastAPI(
    title="Stock Data Intelligence Dashboard API",
    description="REST APIs for stock data collection, processing, and analytics.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent

SYMBOLS = {company["symbol"] for company in COMPANY_MASTER}
REFRESH_CACHE: dict[str, datetime] = {}
REFRESH_TTL = timedelta(minutes=30)

init_db()
bootstrap_companies()


def _assert_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol not in SYMBOLS:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not supported")
    return symbol


def _ensure_recent_data(symbol: str) -> None:
    now = datetime.utcnow()
    last_refresh = REFRESH_CACHE.get(symbol)

    if last_refresh and now - last_refresh < REFRESH_TTL:
        return

    try:
        refresh_symbol(symbol)
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    REFRESH_CACHE[symbol] = now


@app.on_event("startup")
def startup_event() -> None:
    init_db()
    bootstrap_companies()

    for symbol in SYMBOLS:
        try:
            _ensure_recent_data(symbol)
        except Exception:
            continue


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "stock-dashboard-api"}


@app.get("/companies")
def get_companies() -> dict:
    companies = fetch_companies()
    return {"count": len(companies), "companies": companies}


@app.get("/data/{symbol}")
def get_stock_data(
    symbol: str,
    days: int = Query(default=30, ge=7, le=365),
) -> dict:
    symbol = _assert_symbol(symbol)
    _ensure_recent_data(symbol)

    rows = fetch_symbol_data(symbol, days)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data available for {symbol}")

    closes = [row["close"] for row in rows]
    prediction = prediction_points(closes, horizon=7)

    return {
        "symbol": symbol,
        "days": days,
        "points": rows,
        "prediction": prediction,
    }


@app.get("/summary/{symbol}")
def get_summary(symbol: str) -> dict:
    symbol = _assert_symbol(symbol)
    _ensure_recent_data(symbol)

    rows = fetch_symbol_data(symbol, 252)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No summary available for {symbol}")

    closes = [row["close"] for row in rows]
    latest = rows[-1]

    summary = {
        "symbol": symbol,
        "latest_close": round(float(latest["close"]), 2),
        "latest_open": round(float(latest["open"]), 2),
        "latest_daily_return": round(float(latest.get("daily_return") or 0.0), 6),
        "high_52w": round(float(max(row["high"] for row in rows)), 2),
        "low_52w": round(float(min(row["low"] for row in rows)), 2),
        "average_close": round(float(sum(closes) / len(closes)), 2),
        "latest_ma7": round(float(latest.get("ma7") or 0.0), 2),
        "volatility_score": volatility_score(rows),
        "sentiment_index": sentiment_index(rows),
    }
    return summary


@app.get("/compare")
def compare_stocks(
    symbol1: str = Query(...),
    symbol2: str = Query(...),
    days: int = Query(default=30, ge=7, le=180),
) -> dict:
    symbol1 = _assert_symbol(symbol1)
    symbol2 = _assert_symbol(symbol2)

    _ensure_recent_data(symbol1)
    _ensure_recent_data(symbol2)

    first = fetch_symbol_history(symbol1, days)
    second = fetch_symbol_history(symbol2, days)

    if not first or not second:
        raise HTTPException(status_code=404, detail="Comparison data unavailable")

    first_start = float(first[0]["close"])
    first_end = float(first[-1]["close"])
    second_start = float(second[0]["close"])
    second_end = float(second[-1]["close"])

    first_return = ((first_end - first_start) / first_start) * 100 if first_start else 0.0
    second_return = ((second_end - second_start) / second_start) * 100 if second_start else 0.0

    return {
        "symbol1": symbol1,
        "symbol2": symbol2,
        "days": days,
        "series1": first,
        "series2": second,
        "performance": {
            symbol1: round(first_return, 2),
            symbol2: round(second_return, 2),
            "winner": symbol1 if first_return >= second_return else symbol2,
        },
    }


@app.get("/", include_in_schema=False)
def serve_home() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/{file_path:path}", include_in_schema=False)
def serve_static(file_path: str) -> FileResponse:
    candidate = (BASE_DIR / file_path).resolve()
    if not str(candidate).startswith(str(BASE_DIR.resolve())) or not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(candidate)
