from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any
import io
import zipfile
from datetime import datetime

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

from .database import upsert_companies, upsert_stock_rows

COMPANY_MASTER = [
    {"symbol": "RELIANCE", "name": "Reliance Industries", "sector": "Energy"},
    {"symbol": "TCS", "name": "Tata Consultancy Services", "sector": "IT Services"},
    {"symbol": "INFY", "name": "Infosys Ltd.", "sector": "IT Services"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank", "sector": "Banking"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank", "sector": "Banking"},
    {"symbol": "SBIN", "name": "State Bank of India", "sector": "Banking"},
    {"symbol": "ITC", "name": "ITC Ltd.", "sector": "FMCG"},
    {"symbol": "LT", "name": "Larsen & Toubro", "sector": "Engineering"},
    {"symbol": "ASIANPAINT", "name": "Asian Paints", "sector": "Paints"},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever", "sector": "FMCG"},
]


@dataclass
class RefreshResult:
    symbol: str
    source: str
    rows_saved: int


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BHAVCOPY_DIR = DATA_DIR / "bhavcopy"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

NSE_ARCHIVE_BASE_URL = "https://nsearchives.nseindia.com/content/cm"
BHAVCOPY_LOOKBACK_DAYS = int(os.getenv("BHAVCOPY_LOOKBACK_DAYS", "90"))
_BHAVCOPY_SYNC_DONE = False

# yfinance symbol mapping for Indian listings.
YF_SYMBOL_MAP = {company["symbol"]: f"{company['symbol']}.NS" for company in COMPANY_MASTER}


class DataSourceUnavailableError(RuntimeError):
    pass


def bootstrap_companies() -> None:
    upsert_companies(COMPANY_MASTER)


def _download_yfinance_df(symbol: str) -> pd.DataFrame:
    yf_symbol = YF_SYMBOL_MAP.get(symbol, symbol)

    frame = yf.download(
        yf_symbol,
        period="2y",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if frame.empty:
        raise ValueError("No market data returned")

    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

    return frame


def _nse_bhavcopy_filename(trade_date: datetime) -> str:
    return f"BhavCopy_NSE_CM_0_0_0_{trade_date.strftime('%Y%m%d')}_F_0000.csv"


def _download_nse_bhavcopy_csvs() -> int:
    global _BHAVCOPY_SYNC_DONE
    if _BHAVCOPY_SYNC_DONE:
        return 0

    BHAVCOPY_DIR.mkdir(parents=True, exist_ok=True)

    if any(BHAVCOPY_DIR.glob("*.csv")):
        _BHAVCOPY_SYNC_DONE = True
        return 0

    today = datetime.utcnow().date()
    business_days = pd.bdate_range(end=today, periods=BHAVCOPY_LOOKBACK_DAYS)

    downloaded_count = 0
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/zip,application/octet-stream,*/*",
    }

    for business_day in business_days:
        trade_date = business_day.to_pydatetime()
        csv_name = _nse_bhavcopy_filename(trade_date)
        csv_path = BHAVCOPY_DIR / csv_name
        if csv_path.exists():
            continue

        zip_url = f"{NSE_ARCHIVE_BASE_URL}/{csv_name}.zip"
        try:
            response = requests.get(zip_url, headers=headers, timeout=20)
            if response.status_code != 200:
                continue

            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
                if not csv_members:
                    continue
                with archive.open(csv_members[0]) as csv_file:
                    csv_path.write_bytes(csv_file.read())
                    downloaded_count += 1
        except Exception:
            continue

    _BHAVCOPY_SYNC_DONE = True
    return downloaded_count


def _read_bhavcopy_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    normalized_columns = {}
    for col in df.columns:
        key = str(col).strip().lower().replace(" ", "")
        normalized_columns[col] = {
            "tckrsymb": "SYMBOL",
            "symbol": "SYMBOL",
            "series": "SERIES",
            "traddt": "TIMESTAMP",
            "timestamp": "TIMESTAMP",
            "date1": "TIMESTAMP",
            "opnpric": "OPEN",
            "open": "OPEN",
            "hghpric": "HIGH",
            "high": "HIGH",
            "lwpric": "LOW",
            "low": "LOW",
            "clspric": "CLOSE",
            "close": "CLOSE",
            "ttltradgvol": "TOTTRDQTY",
            "tottrdqty": "TOTTRDQTY",
            "tottrdqnty": "TOTTRDQTY",
            "no_of_shrs": "TOTTRDQTY",
            "volume": "TOTTRDQTY",
            "sc_name": "SC_NAME",
        }.get(key, str(col).strip().upper())

    df = df.rename(columns=normalized_columns)
    return df


def _load_bhavcopy_df(symbol: str) -> pd.DataFrame:
    _download_nse_bhavcopy_csvs()

    if not BHAVCOPY_DIR.exists():
        raise ValueError("Bhavcopy directory not found")

    records: list[pd.DataFrame] = []
    csv_files = sorted(BHAVCOPY_DIR.rglob("*.csv"))

    for file in csv_files:
        try:
            raw = _read_bhavcopy_csv(file)
        except Exception:
            continue

        upper_symbol = symbol.upper()

        # NSE format: SYMBOL, OPEN, HIGH, LOW, CLOSE, TOTTRDQTY, TIMESTAMP.
        if {"SYMBOL", "OPEN", "HIGH", "LOW", "CLOSE"}.issubset(raw.columns):
            nse = raw[raw["SYMBOL"].astype(str).str.upper() == upper_symbol].copy()
            if nse.empty:
                continue
            if "SERIES" in nse.columns:
                nse = nse[nse["SERIES"].astype(str).str.upper() == "EQ"]
                if nse.empty:
                    continue
            if "TIMESTAMP" in nse.columns:
                nse["Date"] = pd.to_datetime(nse["TIMESTAMP"], errors="coerce")
            elif "DATE1" in nse.columns:
                nse["Date"] = pd.to_datetime(nse["DATE1"], errors="coerce")
            else:
                continue
            nse["Volume"] = pd.to_numeric(
                nse.get("TOTTRDQTY", nse.get("NO_OF_SHRS", 0)), errors="coerce"
            )
            records.append(
                nse[["Date", "OPEN", "HIGH", "LOW", "CLOSE", "Volume"]].rename(
                    columns={
                        "OPEN": "Open",
                        "HIGH": "High",
                        "LOW": "Low",
                        "CLOSE": "Close",
                    }
                )
            )
            continue

        # BSE-like fallback: SC_NAME, OPEN, HIGH, LOW, CLOSE, NO_OF_SHRS, DATE1.
        if {"SC_NAME", "OPEN", "HIGH", "LOW", "CLOSE"}.issubset(raw.columns):
            bse = raw[raw["SC_NAME"].astype(str).str.upper().str.contains(upper_symbol)].copy()
            if bse.empty:
                continue
            if "DATE1" in bse.columns:
                bse["Date"] = pd.to_datetime(bse["DATE1"], errors="coerce")
            else:
                continue
            bse["Volume"] = pd.to_numeric(bse.get("NO_OF_SHRS", 0), errors="coerce")
            records.append(
                bse[["Date", "OPEN", "HIGH", "LOW", "CLOSE", "Volume"]].rename(
                    columns={
                        "OPEN": "Open",
                        "HIGH": "High",
                        "LOW": "Low",
                        "CLOSE": "Close",
                    }
                )
            )

    if not records:
        raise ValueError(f"No bhavcopy rows found for {symbol}")

    result = pd.concat(records, ignore_index=True)
    result = result.drop_duplicates(subset=["Date"]).sort_values("Date")
    return result.set_index("Date")


def _download_alpha_vantage_df(symbol: str) -> pd.DataFrame:
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise ValueError("ALPHA_VANTAGE_API_KEY is not configured")

    response = requests.get(
        "https://www.alphavantage.co/query",
        params={
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": symbol,
            "outputsize": "full",
            "apikey": api_key,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    if "Time Series (Daily)" not in payload:
        message = payload.get("Note") or payload.get("Information") or "Alpha Vantage response missing timeseries"
        raise ValueError(message)

    rows = []
    for trade_date, values in payload["Time Series (Daily)"].items():
        rows.append(
            {
                "Date": trade_date,
                "Open": values.get("1. open"),
                "High": values.get("2. high"),
                "Low": values.get("3. low"),
                "Close": values.get("4. close"),
                "Volume": values.get("6. volume"),
            }
        )

    if not rows:
        raise ValueError("No Alpha Vantage rows returned")

    frame = pd.DataFrame(rows)
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.set_index("Date").sort_index()
    return frame


def _clean_and_feature_engineer(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Normalize mixed-case provider columns into a predictable schema.
    df.columns = [str(col).strip().title() for col in df.columns]

    if "Date" not in df.columns:
        df = df.reset_index()

    df = df.rename(
        columns={
            "Date": "trade_date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )

    keep_cols = ["trade_date", "open", "high", "low", "close", "volume"]
    df = df[keep_cols]

    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Cleaning: remove rows with invalid dates/prices and fill sparse volume gaps.
    df = df.dropna(subset=["trade_date", "open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0)
    df = df.sort_values("trade_date")

    df = df[df["open"] > 0]

    df["daily_return"] = (df["close"] - df["open"]) / df["open"]
    df["ma7"] = df["close"].rolling(7, min_periods=1).mean()
    df["high_52w"] = df["high"].rolling(252, min_periods=1).max()
    df["low_52w"] = df["low"].rolling(252, min_periods=1).min()

    df["trade_date"] = df["trade_date"].dt.strftime("%Y-%m-%d")
    return df


def refresh_symbol(symbol: str) -> RefreshResult:
    source = ""
    downloaded: pd.DataFrame | None = None

    data_sources = [
        ("nse_bse_bhavcopy", _load_bhavcopy_df),
        ("yfinance", _download_yfinance_df),
        ("alpha_vantage", _download_alpha_vantage_df),
    ]

    errors: list[str] = []
    for source_name, loader in data_sources:
        try:
            candidate = loader(symbol)
            if candidate is None or candidate.empty:
                raise ValueError("Source returned empty frame")
            downloaded = candidate
            source = source_name
            break
        except Exception as exc:
            errors.append(f"{source_name}: {exc}")

    if downloaded is None:
        raise DataSourceUnavailableError(
            f"Unable to fetch real data for {symbol}. "
            f"Tried sources -> {' | '.join(errors)}"
        )

    cleaned = _clean_and_feature_engineer(downloaded)

    if cleaned.empty:
        raise DataSourceUnavailableError(f"All rows were dropped during cleaning for {symbol}")

    rows = cleaned.to_dict(orient="records")
    upsert_stock_rows(symbol, rows)
    return RefreshResult(symbol=symbol, source=source, rows_saved=len(rows))


def volatility_score(data_rows: list[dict[str, Any]]) -> float:
    if not data_rows:
        return 0.0
    series = pd.Series([row.get("daily_return") for row in data_rows], dtype="float64").dropna()
    if len(series) < 2:
        return 0.0
    annualized = float(series.std(ddof=1) * np.sqrt(252))
    return round(annualized, 4)


def sentiment_index(data_rows: list[dict[str, Any]]) -> float:
    if len(data_rows) < 2:
        return 50.0

    closes = pd.Series([row["close"] for row in data_rows], dtype="float64")
    returns = closes.pct_change().dropna()
    if returns.empty:
        return 50.0

    momentum = float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0])
    consistency = float((returns > 0).mean())

    score = (0.6 * (momentum * 100 + 50)) + (0.4 * (consistency * 100))
    return round(max(0.0, min(100.0, score)), 2)


def prediction_points(closes: list[float], horizon: int = 7) -> list[float]:
    if len(closes) < 3:
        return []

    x = np.arange(len(closes), dtype=float)
    y = np.array(closes, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)

    future_idx = np.arange(len(closes), len(closes) + horizon, dtype=float)
    forecast = slope * future_idx + intercept
    return [round(float(value), 2) for value in forecast]
