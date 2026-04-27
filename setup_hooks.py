#!/usr/bin/env python3
"""
Setup script to configure PostToolUse hooks for Sutra agents.
This enables Claude Code to report tool usage events to the Sutra API.

Usage:
  python3 setup_hooks.py --agent-cwd /path/to/agent/workspace
  python3 setup_hooks.py --sutra-agent

When configured, Claude Code instances spawned in the agent's workspace
will send PostToolUse events to http://localhost:8910/api/events, allowing
the Sutra timeline UI to display which tools are currently being used.
"""

import json
import sys
import os
from pathlib import Path
import argparse


def setup_agent_hooks(agent_cwd, api_url="http://localhost:8910/api/events"):
    """
    Configure PostToolUse hook in an agent's .claude/settings.json

    Args:
        agent_cwd: Path to the agent's workspace directory
        api_url: URL of the POST /api/events endpoint
    """
    settings_dir = Path(agent_cwd) / ".claude"
    settings_file = settings_dir / "settings.json"

    # Create .claude directory if it doesn't exist
    settings_dir.mkdir(parents=True, exist_ok=True)

    # Load existing settings or create new ones
    if settings_file.exists():
        with open(settings_file, 'r') as f:
            settings = json.load(f)
    else:
        settings = {"permissions": {"allow": ["Bash(*)", "Read(*)", "Write(*)", "Edit(*)", "Glob(*)", "Grep(*)"]}}

    # Add or update hooks section
    if "hooks" not in settings:
        settings["hooks"] = {}

    # Configure PostToolUse hook
    settings["hooks"]["PostToolUse"] = [
        {
            "matcher": "*",
            "hooks": [
                {
                    "type": "http",
                    "url": api_url,
                    "headers": {"Authorization": "Bearer $SUTRA_TOKEN"}
                }
            ]
        }
    ]

    # Write updated settings back
    with open(settings_file, 'w') as f:
        json.dump(settings, f, indent=2)

    print(f"✓ Configured PostToolUse hook for {agent_cwd}")
    print(f"  Settings saved to: {settings_file}")
    print(f"  Endpoint: {api_url}")
    return True


def setup_sutra_agent_hooks(api_url="http://localhost:8910/api/events"):
    """
    Configure hooks for the main Sutra agent (default location).
    """
    sutra_cwd = os.path.expanduser("~/Downloads/personal-os-main")
    return setup_agent_hooks(sutra_cwd, api_url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup PostToolUse hooks for Sutra agents")
    parser.add_argument("--agent-cwd", type=str, help="Path to agent workspace to configure")
    parser.add_argument("--sutra-agent", action="store_true", help="Setup hook for default Sutra agent")
    parser.add_argument("--api-url", type=str, default="http://localhost:8910/api/events",
                       help="URL of POST /api/events endpoint")

    args = parser.parse_args()

    if args.sutra_agent:
        setup_sutra_agent_hooks(args.api_url)
    elif args.agent_cwd:
        setup_agent_hooks(args.agent_cwd, args.api_url)
    else:
        print("Error: specify --agent-cwd or --sutra-agent")
        sys.exit(1)
