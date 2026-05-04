from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from meeseeks.contracts import TokenUsage

DB_PATH = Path.home() / ".meeseeks" / "budget.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            meeseeks_name TEXT NOT NULL,
            meeseeks_id TEXT NOT NULL,
            status TEXT NOT NULL,
            llm_cost_usd REAL NOT NULL DEFAULT 0,
            tool_cost_usd REAL NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def record_run(
    meeseeks_name: str,
    meeseeks_id: str,
    status: str,
    cost: TokenUsage,
    duration_ms: int,
) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO runs (ts, meeseeks_name, meeseeks_id, status, llm_cost_usd, tool_cost_usd, total_tokens, duration_ms) VALUES (?,?,?,?,?,?,?,?)",
            (int(time.time()), meeseeks_name, meeseeks_id, status, cost.cost_usd, cost.tool_cost_usd, cost.total_tokens, duration_ms),
        )


def today_total() -> float:
    midnight = int(time.time()) - (int(time.time()) % 86400)
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(llm_cost_usd + tool_cost_usd), 0) FROM runs WHERE ts >= ?",
            (midnight,),
        ).fetchone()
    return row[0]


def cost_breakdown(days: int = 1) -> dict:
    since = int(time.time()) - days * 86400
    with _conn() as conn:
        rows = conn.execute(
            "SELECT meeseeks_name, COUNT(*), SUM(llm_cost_usd), SUM(tool_cost_usd), SUM(total_tokens) FROM runs WHERE ts >= ? GROUP BY meeseeks_name",
            (since,),
        ).fetchall()
    return {
        row[0]: {
            "spawns": row[1],
            "llm_cost": round(row[2], 4),
            "tool_cost": round(row[3], 4),
            "tokens": row[4],
        }
        for row in rows
    }
