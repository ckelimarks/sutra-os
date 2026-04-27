# Claude Code Session JSONL Structure

One JSON object per line. Each entry has a `type` field that determines its structure.

```
┌─────────────────────────────────────────────────────────┐
│                    SESSION.JSONL                        │
│                 (one JSON object per line)               │
└───────────────────────┬─────────────────────────────────┘
                        │
    ┌───────────────────┼───────────────────────┐
    │                   │                       │
    ▼                   ▼                       ▼
 SYSTEM              TURNS                   METADATA
 (startup)        (repeat N)              (end markers)
```

---

## Startup Phase

```
  ⚙ system/hook_started     SessionStart hook fires
  ⚙ system/hook_response    Hook output (session registered)
  ⚙ system/init             Session ID, model, tools, cwd, skills
  📋 queue-operation          Internal queue state
```

---

## Conversation Turn (repeats)

```
  👤 user
  │  message.content = "your text here"     ← plain string
  │
  🤖 assistant
  │  message.content = [                    ← ARRAY of blocks
  │    │
  │    ├── {type: "thinking"}               ← model's reasoning
  │    │     .thinking = "Let me consider..."  (collapsible)
  │    │
  │    ├── {type: "text"}                   ← response prose
  │    │     .text = "Here's what I found..." (render as markdown)
  │    │
  │    ├── {type: "tool_use"}               ← tool invocation
  │    │     .name = "Bash"
  │    │     .id = "toolu_01..."
  │    │     .input = {command: "ls -la"}
  │    │
  │    ├── {type: "tool_result"}            ← tool output
  │    │     .tool_use_id = "toolu_01..."
  │    │     .content = "file1.txt\nfile2.py"
  │    │
  │    ├── {type: "tool_use"}               ← can chain multiple
  │    │     .name = "Read"
  │    │     .input = {file_path: "/path"}
  │    │
  │    ├── {type: "tool_result"}
  │    │     .content = "file contents..."
  │    │
  │    └── {type: "text"}                   ← final response
  │          .text = "Done. Here's the summary."
  │
  │  message.usage = {
  │    input_tokens: 1234,
  │    output_tokens: 567,
  │    cache_creation_input_tokens: 8901,   ← context window
  │    cache_read_input_tokens: 2345        ← cache hits
  │  }
  │
  📊 result
  │  .total_cost_usd = 0.0834
  │  .duration_ms = 4521
  │  .num_turns = 1
  │  .session_id = "abc123..."
  │  .usage = { ... }                       ← aggregate
  │  .modelUsage = { ... }                  ← per-model breakdown
  │
  ⏳ progress                                ← skip (loading spinners)
  📁 file-history-snapshot                   ← skip (file state captures)
  ⚙ system/stop_hook_summary               ← between turns

  (repeat: user → assistant → result)
```

---

## End of Session

```
  💬 last-prompt              Last user message (bookmark)
```

---

## Tool Types & Their Inputs

| Tool | Input Fields | Example |
|------|-------------|---------|
| `Bash` | `{command}` | `{command: "npm test"}` |
| `Read` | `{file_path, offset?, limit?}` | `{file_path: "/abs/path", limit: 100}` |
| `Write` | `{file_path, content}` | `{file_path: "/abs/path", content: "..."}` |
| `Edit` | `{file_path, old_string, new_string}` | `{file_path: "/abs/path", old_string: "...", new_string: "..."}` |
| `Glob` | `{pattern, path?}` | `{pattern: "**/*.ts", path: "/dir"}` |
| `Grep` | `{pattern, path?, type?}` | `{pattern: "regex", path: "/dir", type: "ts"}` |
| `WebFetch` | `{url, prompt}` | `{url: "https://...", prompt: "extract X"}` |
| `WebSearch` | `{query}` | `{query: "search terms"}` |
| `Agent` | `{prompt, subagent_type?}` | `{prompt: "task", subagent_type: "general"}` |
| `Skill` | `{skill, args?}` | `{skill: "save", args: ""}` |

---

## Context Window Calculation

```
Context Window = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
```

This is what fills up and triggers compaction at ~80% of the model's limit.

| Model | Max Context |
|-------|-------------|
| Opus 4.6 | 1,000,000 |
| Sonnet 4.6 | 200,000 |
| Haiku 4.5 | 200,000 |

---

## Entry Types to Skip

- `progress` — loading spinners, no content
- `file-history-snapshot` — file state captures, internal bookkeeping
- `queue-operation` — internal queue state

## Entry Types to Render

- `user` — user message (content is a plain string)
- `assistant` — response (content is an array of typed blocks)
- `system` — hooks, init events (show as dim metadata)
- `result` — cost/usage summary card

---

## Stream-JSON vs Stored JSONL

When using `claude --output-format stream-json`, the events arrive in real-time with slightly different structure:

| Stream Event | Stored JSONL |
|-------------|-------------|
| `type: "system", subtype: "init"` | Same |
| `type: "assistant"` (with content blocks) | Same, but arrives incrementally |
| `type: "rate_limit_event"` | Not stored in JSONL |
| `type: "result"` | Same |

The `rate_limit_event` is stream-only and contains:
```json
{
  "rate_limit_info": {
    "status": "allowed",
    "resetsAt": 1776063600,
    "rateLimitType": "five_hour",
    "overageStatus": "allowed",
    "overageResetsAt": 1777593600
  }
}
```
