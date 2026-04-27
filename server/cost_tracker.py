"""
Cost Tracker for Sutra Orchestrator.
Pure functions for aggregating and querying costs.
All functions take a sqlite3 connection as first arg.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional


def get_period_start(period: str) -> Optional[str]:
    """Return ISO datetime string for the start of a time period.

    Args:
        period: 'daily' | 'weekly' | 'monthly' | 'all'

    Returns:
        ISO datetime string, or None for 'all'
    """
    now = datetime.now(timezone.utc)
    if period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        start = now - timedelta(days=7)
    elif period == "monthly":
        start = now - timedelta(days=30)
    elif period == "all":
        return None
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat()


def get_agent_cost(conn: sqlite3.Connection, agent_id: str, period: str = "daily") -> dict:
    """Get cost for a single agent over a time period.

    Returns: {agent_id, agent_name, cost_usd, message_count, period, since}
    """
    since = get_period_start(period)

    if since:
        row = conn.execute("""
            SELECT a.name, COALESCE(SUM(m.cost_usd), 0) as cost,
                   COUNT(m.id) as msg_count
            FROM agents a
            LEFT JOIN threads t ON t.agent_id = a.id
            LEFT JOIN messages m ON m.thread_id = t.id AND m.created_at >= ?
            WHERE a.id = ?
            GROUP BY a.id
        """, (since, agent_id)).fetchone()
    else:
        row = conn.execute("""
            SELECT a.name, COALESCE(SUM(m.cost_usd), 0) as cost,
                   COUNT(m.id) as msg_count
            FROM agents a
            LEFT JOIN threads t ON t.agent_id = a.id
            LEFT JOIN messages m ON m.thread_id = t.id
            WHERE a.id = ?
            GROUP BY a.id
        """, (agent_id,)).fetchone()

    if not row:
        return {"agent_id": agent_id, "agent_name": "unknown", "cost_usd": 0.0,
                "message_count": 0, "period": period, "since": since}

    return {
        "agent_id": agent_id,
        "agent_name": row[0],
        "cost_usd": round(row[1], 6),
        "message_count": row[2],
        "period": period,
        "since": since,
    }


def get_all_costs(conn: sqlite3.Connection, period: str = "daily") -> list:
    """Get costs for all agents, sorted by cost descending."""
    since = get_period_start(period)

    if since:
        rows = conn.execute("""
            SELECT a.id, a.name, COALESCE(SUM(m.cost_usd), 0) as cost,
                   COUNT(m.id) as msg_count
            FROM agents a
            LEFT JOIN threads t ON t.agent_id = a.id
            LEFT JOIN messages m ON m.thread_id = t.id AND m.created_at >= ?
            GROUP BY a.id
            ORDER BY cost DESC
        """, (since,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT a.id, a.name, COALESCE(SUM(m.cost_usd), 0) as cost,
                   COUNT(m.id) as msg_count
            FROM agents a
            LEFT JOIN threads t ON t.agent_id = a.id
            LEFT JOIN messages m ON m.thread_id = t.id
            GROUP BY a.id
            ORDER BY cost DESC
        """).fetchall()

    return [
        {
            "agent_id": r[0],
            "agent_name": r[1],
            "cost_usd": round(r[2], 6),
            "message_count": r[3],
            "period": period,
            "since": since,
        }
        for r in rows
    ]


def get_cost_breakdown(conn: sqlite3.Connection, period: str = "daily") -> dict:
    """Full cost breakdown: total, per-agent, per-model.

    Returns: {total_usd, period, since, by_agent: [...], by_model: [...]}
    """
    since = get_period_start(period)

    # Per-agent
    by_agent = get_all_costs(conn, period)

    # Per-model
    if since:
        model_rows = conn.execute("""
            SELECT a.model, COALESCE(SUM(m.cost_usd), 0) as cost,
                   COUNT(m.id) as msg_count
            FROM messages m
            JOIN threads t ON t.id = m.thread_id
            JOIN agents a ON a.id = t.agent_id
            WHERE m.created_at >= ?
            GROUP BY a.model
            ORDER BY cost DESC
        """, (since,)).fetchall()
    else:
        model_rows = conn.execute("""
            SELECT a.model, COALESCE(SUM(m.cost_usd), 0) as cost,
                   COUNT(m.id) as msg_count
            FROM messages m
            JOIN threads t ON t.id = m.thread_id
            JOIN agents a ON a.id = t.agent_id
            GROUP BY a.model
            ORDER BY cost DESC
        """).fetchall()

    by_model = [
        {"model": r[0], "cost_usd": round(r[1], 6), "messages": r[2]}
        for r in model_rows
    ]

    total = sum(a["cost_usd"] for a in by_agent)

    return {
        "total_usd": round(total, 6),
        "period": period,
        "since": since,
        "by_agent": by_agent,
        "by_model": by_model,
    }


def check_budget(
    conn: sqlite3.Connection,
    budget_usd: float,
    period: str = "daily",
) -> dict:
    """Check if spending is approaching budget.

    Returns: {spent_usd, budget_usd, remaining_usd, pct_used, alert}
    alert is True when >80% of budget is used.
    """
    breakdown = get_cost_breakdown(conn, period)
    spent = breakdown["total_usd"]
    remaining = max(0.0, budget_usd - spent)
    pct = (spent / budget_usd * 100) if budget_usd > 0 else 0.0

    return {
        "spent_usd": round(spent, 6),
        "budget_usd": budget_usd,
        "remaining_usd": round(remaining, 6),
        "pct_used": round(pct, 1),
        "alert": pct > 80.0,
        "period": period,
    }
