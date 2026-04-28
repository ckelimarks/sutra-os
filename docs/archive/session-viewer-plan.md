# Plan: Session Viewer Integration

## Goal
View any agent's CC session JSONL from within Sutra's UI — current session, spoofed sessions, historical sessions.

## What Exists
- `web/session-viewer.html` — standalone viewer (drag-and-drop, file picker)
- `GET /api/agents/{id}/context` — context % per agent
- Session files live at `~/.claude/projects/{mangled-cwd}/{session_id}.jsonl`
- DB tracks current session_id per agent in `threads` table
- Spoof tool outputs new session_id to stdout

## New Endpoints

### `GET /api/session-files?agent_id={id}`
Lists all session JSONL files for an agent (by cwd).
Returns: `[{session_id, file_path, size_bytes, mtime, is_current, is_spoofed, lines}]`
- `is_current`: matches the thread's current session_id
- `is_spoofed`: first line contains "Who are you?" (spoof signature)
- Sorted by mtime descending

### `GET /api/session-file/{session_id}?cwd={mangled}`
Returns the raw JSONL content for a specific session.
Content-Type: text/plain (so the viewer can fetch and parse it).

### `GET /session-viewer`
Serves session-viewer.html from the web directory.
When query param `?session={id}&cwd={mangled}` is present, auto-loads that session.

## UI Integration Points

### 1. Drawer header — "View Session" button
Next to the close button in the drawer header.
Opens `session-viewer.html?session={current_session_id}&cwd={agent_cwd}` in a new tab.
Only shown when agent has a session.

### 2. Lane label — right-click context menu or icon
Small icon on hover that opens the session viewer for that agent.

### 3. Post-spoof — auto-open
After `/spoof` completes, the new session ID opens in the viewer automatically.

### 4. Sessions list in drawer — new "Sessions" tab
Lists all session files for the agent:
```
 Current: 8cd431da (25 turns, 52KB, 2:30 PM)
 Spoofed: 4182f027 (684 entries, 2.0MB, 1:15 PM)
 Old:     a2f05d30 (156 entries, 891KB, Apr 12)
```
Click any to open in session viewer.

## Session Viewer Improvements

### Auto-load from URL params
```javascript
const params = new URLSearchParams(window.location.search);
const sessionId = params.get('session');
const cwd = params.get('cwd');
if (sessionId && cwd) {
  fetch(`/api/session-file/${sessionId}?cwd=${cwd}`)
    .then(r => r.text())
    .then(text => parseAndRender(text));
}
```

### Context meter
Show at the top of the viewer:
- Total input_tokens from the last assistant message
- Context window size (based on model)
- Visual bar matching the drawer style

### Session metadata sidebar
Instead of just drag-and-drop info, show:
- Session ID
- Agent name (from first system event or DB lookup)
- CWD
- Model
- Whether spoofed
- Total cost
- Total turns
- Created / last modified

## Implementation Order

1. Add `GET /api/session-files` and `GET /api/session-file/{id}` endpoints to bridge.py
2. Add auto-load from URL params to session-viewer.html
3. Add "View Session" button to drawer header
4. Add "Sessions" tab to drawer
5. Add context meter to session viewer
6. Wire post-spoof auto-open (future — needs spoof integration)

## Files to Touch
- `server/bridge.py` — 2 new endpoints
- `web/session-viewer.html` — URL param loading, context meter
- `web/index.html` — drawer "View Session" button + Sessions tab
