#!/usr/bin/env python3
"""Sutra statusline — output for Claude Code customStatusCommand (REQ-3.4)

Prints one line to stdout. Claude Code displays it in the status bar.
Falls back to "Sutra: offline" if server is unreachable.
"""
import urllib.request
import json
import sys

PORT = 8900


def fetch(path):
    url = f"http://localhost:{PORT}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=1) as r:
        return json.loads(r.read())


def main():
    try:
        agents_data = fetch("/api/agents")
        usage_data = fetch("/api/usage?period=daily")
        reports_data = fetch("/api/reports?acknowledged=false")
    except Exception:
        print("Sutra: offline")
        return

    agents = agents_data.get("agents", [])
    active_count = sum(1 for a in agents if a.get("status") in ("idle", "busy"))

    total_cost = usage_data.get("total_usd", 0.0)

    reports = reports_data.get("reports", [])
    # Priority order: error first, then needs_input, complete, checkpoint, decision
    type_order = {"error": 0, "needs_input": 1, "complete": 2, "checkpoint": 3, "decision": 4}
    reports.sort(key=lambda r: type_order.get(r.get("type", ""), 99))

    parts = [f"{active_count} agents", f"${total_cost:.2f}"]

    if reports:
        top = reports[0]
        summary = (top.get("summary") or "")[:60].strip()
        agent_name = (top.get("agent_name") or "").strip()
        if summary:
            label = f"{agent_name}: {summary}" if agent_name else summary
            parts.append(label)

    print("Sutra: " + " | ".join(parts))


if __name__ == "__main__":
    main()
