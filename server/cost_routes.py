"""
Cost API route handlers for Sutra Orchestrator.
Standalone functions that return (response_dict, status_code).
Wire into bridge.py's GET handler.
"""

import db
import cost_tracker


def handle_get_usage(query_params: dict) -> tuple[dict, int]:
    """Handler for GET /api/usage

    Query params:
        period: daily | weekly | monthly | all (default: daily)

    Returns: (response_dict, status_code)
    """
    period = query_params.get("period", ["daily"])[0]

    if period not in ("daily", "weekly", "monthly", "all"):
        return {"error": f"Invalid period: {period}"}, 400

    with db.get_connection() as conn:
        breakdown = cost_tracker.get_cost_breakdown(conn, period)

    return breakdown, 200


def handle_get_budget(query_params: dict) -> tuple[dict, int]:
    """Handler for GET /api/budget

    Query params:
        budget: float (required) — budget cap in USD
        period: daily | weekly | monthly | all (default: daily)

    Returns: (response_dict, status_code)
    """
    budget_raw = query_params.get("budget", [None])[0]
    if budget_raw is None:
        return {"error": "Missing required param: budget"}, 400

    try:
        budget_usd = float(budget_raw)
    except (ValueError, TypeError):
        return {"error": f"Invalid budget value: {budget_raw}"}, 400

    period = query_params.get("period", ["daily"])[0]

    with db.get_connection() as conn:
        result = cost_tracker.check_budget(conn, budget_usd, period)

    return result, 200
