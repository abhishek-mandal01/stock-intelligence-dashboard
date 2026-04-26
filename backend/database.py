from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

DB_PATH = Path(__file__).resolve().parent / "stocks.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS companies (
                symbol TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                sector TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_prices (
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                daily_return REAL,
                ma7 REAL,
                high_52w REAL,
                low_52w REAL,
                PRIMARY KEY (symbol, trade_date)
            )
            """
        )


def upsert_companies(companies: Iterable[dict]) -> None:
    payload = [
        (company["symbol"], company["name"], company["sector"])
        for company in companies
    ]
    symbols = [row[0] for row in payload]

    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO companies(symbol, name, sector)
            VALUES (?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
              name = excluded.name,
              sector = excluded.sector
            """,
            payload,
        )

        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            conn.execute(
                f"DELETE FROM companies WHERE symbol NOT IN ({placeholders})",
                symbols,
            )
            conn.execute(
                f"DELETE FROM stock_prices WHERE symbol NOT IN ({placeholders})",
                symbols,
            )


def upsert_stock_rows(symbol: str, rows: Iterable[dict]) -> None:
    payload = [
        (
            symbol,
            row["trade_date"],
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            row["volume"],
            row.get("daily_return"),
            row.get("ma7"),
            row.get("high_52w"),
            row.get("low_52w"),
        )
        for row in rows
    ]

    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO stock_prices(
                symbol,
                trade_date,
                open,
                high,
                low,
                close,
                volume,
                daily_return,
                ma7,
                high_52w,
                low_52w
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, trade_date) DO UPDATE SET
              open = excluded.open,
              high = excluded.high,
              low = excluded.low,
              close = excluded.close,
              volume = excluded.volume,
              daily_return = excluded.daily_return,
              ma7 = excluded.ma7,
              high_52w = excluded.high_52w,
              low_52w = excluded.low_52w
            """,
            payload,
        )


def fetch_companies() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.symbol, c.name, c.sector,
                   sp.close AS latest_close,
                   sp.daily_return AS latest_daily_return
            FROM companies c
            LEFT JOIN stock_prices sp
              ON c.symbol = sp.symbol
             AND sp.trade_date = (
                SELECT MAX(s2.trade_date)
                FROM stock_prices s2
                WHERE s2.symbol = c.symbol
             )
            ORDER BY c.symbol
            """
        ).fetchall()

    result = []
    for row in rows:
        result.append(
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "sector": row["sector"],
                "latest_close": row["latest_close"],
                "latest_daily_return": row["latest_daily_return"],
            }
        )
    return result


def fetch_symbol_data(symbol: str, days: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT trade_date, open, high, low, close, volume,
                   daily_return, ma7, high_52w, low_52w
            FROM stock_prices
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (symbol, days),
        ).fetchall()

    # Return oldest-first for chart rendering.
    rows = list(reversed(rows))
    return [dict(row) for row in rows]


def fetch_symbol_history(symbol: str, days: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT trade_date, close, daily_return
            FROM stock_prices
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (symbol, days),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]
