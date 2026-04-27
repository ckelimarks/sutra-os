"""
Workspace Manager for Sutra Orchestrator.
Git-backed, permissioned agent workspaces.
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

WORKSPACES_DIR = Path(__file__).parent.parent / "data" / "workspaces"

# Permission tiers → .claude/settings.json content
TIER_SETTINGS = {
    "autonomous": {
        "permissions": {
            "allow": [
                "Bash(*)",
                "Read(*)",
                "Write(*)",
                "Edit(*)",
                "Glob(*)",
                "Grep(*)",
            ],
            "deny": [
                "Bash(rm -rf /)",
                "Bash(git push --force*)",
                "Bash(git reset --hard*)",
            ]
        }
    },
    "supervised": {
        "permissions": {
            "allow": [
                "Read(*)",
                "Write(*)",
                "Edit(*)",
                "Glob(*)",
                "Grep(*)",
                "Bash(*)",
            ],
            "deny": [
                "Bash(rm -rf *)",
                "Bash(git push --force*)",
                "Bash(git reset --hard*)",
                "Bash(DROP TABLE*)",
                "Bash(DELETE FROM*)",
            ]
        }
    },
    "restricted": {
        "permissions": {
            "allow": [
                "Read(*)",
                "Glob(*)",
                "Grep(*)",
            ],
            "deny": [
                "Bash(*)",
                "Write(*)",
                "Edit(*)",
            ]
        }
    },
}


def init_workspace(
    agent_name: str,
    permission_tier: str = "autonomous",
) -> Path:
    """Initialize a git-backed workspace for an agent.

    Creates directory, git init, initial commit, and settings.json.
    If workspace already exists, reuses it (no wipe).

    Returns the workspace path.
    """
    workspace = WORKSPACES_DIR / agent_name
    workspace.mkdir(parents=True, exist_ok=True)

    git_dir = workspace / ".git"
    if not git_dir.exists():
        # git init
        _run_git(workspace, ["init"])
        # Create initial .gitignore
        gitignore = workspace / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n.env\nnode_modules/\n")
        _run_git(workspace, ["add", ".gitignore"])
        _run_git(workspace, ["commit", "-m", "Workspace initialized"])
        logger.info(f"Initialized workspace for {agent_name} at {workspace}")
    else:
        logger.info(f"Reusing existing workspace for {agent_name} at {workspace}")

    # Write/update settings.json
    _write_settings(workspace, permission_tier)

    return workspace


def _write_settings(workspace: Path, tier: str):
    """Write .claude/settings.json based on permission tier."""
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(exist_ok=True)

    settings = TIER_SETTINGS.get(tier, TIER_SETTINGS["autonomous"])
    settings_path = claude_dir / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    # Write hook scripts (REQ-3.1)
    _write_hooks(workspace)


def _write_hooks(workspace: Path):
    """Write Claude Code hook scripts for event capture."""
    hooks_dir = workspace / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Extract agent name from workspace path
    agent_name = workspace.name

    hook_template = '''#!/bin/bash
# Auto-generated hook for Sutra observability (REQ-3.1)
# Posts event to Sutra server. Exits 0 on failure (never blocks agent).
AGENT_NAME="{agent_name}"
EVENT_TYPE="{event_type}"
curl -s -X POST http://localhost:8890/api/events \\
  -H "Content-Type: application/json" \\
  -d '{{"agent_id":"'"$AGENT_NAME"'","event_type":"'"$EVENT_TYPE"'","metadata":{{"hook":true}}}}' \\
  > /dev/null 2>&1 || true
'''

    hook_events = ['PostToolUse', 'SubagentStart', 'SubagentStop', 'PreCompact', 'Stop']
    for event in hook_events:
        hook_path = hooks_dir / f"{event}.sh"
        hook_path.write_text(hook_template.format(agent_name=agent_name, event_type=event))
        hook_path.chmod(0o755)


def auto_commit(
    agent_name: str,
    summary: str,
) -> Optional[str]:
    """Auto-commit all changes in an agent's workspace.

    Returns the commit SHA if changes were committed, None if no changes.
    """
    workspace = WORKSPACES_DIR / agent_name
    if not workspace.exists():
        logger.warning(f"Workspace not found for {agent_name}")
        return None

    try:
        # Check for changes
        result = _run_git(workspace, ["status", "--porcelain"])
        if not result.strip():
            return None  # No changes

        # Stage all changes
        _run_git(workspace, ["add", "-A"])

        # Commit
        msg = f"[{agent_name}] {summary}"
        _run_git(workspace, ["commit", "-m", msg])

        # Get commit SHA
        sha = _run_git(workspace, ["rev-parse", "HEAD"]).strip()
        logger.info(f"Auto-committed {sha[:8]} for {agent_name}: {summary}")
        return sha

    except Exception as e:
        logger.warning(f"Auto-commit failed for {agent_name}: {e}")
        return None


def get_commits(
    agent_name: str,
    limit: int = 20,
) -> List[Dict[str, str]]:
    """Get recent commits from an agent's workspace."""
    workspace = WORKSPACES_DIR / agent_name
    if not workspace.exists() or not (workspace / ".git").exists():
        return []

    try:
        result = _run_git(
            workspace,
            ["log", f"--max-count={limit}", "--format=%H|%s|%ai"]
        )
        commits = []
        for line in result.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) >= 3:
                commits.append({
                    "sha": parts[0],
                    "message": parts[1],
                    "date": parts[2],
                })
        return commits
    except Exception as e:
        logger.warning(f"Failed to get commits for {agent_name}: {e}")
        return []


def rollback(
    agent_name: str,
    target_sha: str,
) -> Dict[str, Any]:
    """Rollback workspace to a target commit using git revert.

    Uses revert (not reset --hard) to preserve history.
    Returns {"success": bool, "sha": str, "error": str}
    """
    workspace = WORKSPACES_DIR / agent_name
    if not workspace.exists():
        return {"success": False, "error": "Workspace not found"}

    try:
        # Get current HEAD
        current = _run_git(workspace, ["rev-parse", "HEAD"]).strip()

        if current == target_sha:
            return {"success": True, "sha": current, "message": "Already at target commit"}

        # Get list of commits to revert (from HEAD back to target, exclusive)
        commits_to_revert = _run_git(
            workspace, ["rev-list", f"{target_sha}..HEAD"]
        ).strip().split("\n")

        if not commits_to_revert or commits_to_revert == ['']:
            return {"success": False, "error": "Target commit not found in history"}

        # Revert each commit in order (newest first)
        for sha in commits_to_revert:
            if not sha:
                continue
            try:
                _run_git(workspace, ["revert", "--no-edit", sha])
            except Exception as e:
                # Abort revert on conflict
                try:
                    _run_git(workspace, ["revert", "--abort"])
                except Exception:
                    pass
                return {
                    "success": False,
                    "error": f"Merge conflict reverting {sha[:8]}: {e}",
                    "conflicting_commit": sha,
                }

        new_head = _run_git(workspace, ["rev-parse", "HEAD"]).strip()
        return {"success": True, "sha": new_head, "message": f"Reverted to {target_sha[:8]}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _run_git(workspace: Path, args: List[str]) -> str:
    """Run a git command in a workspace directory."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout
