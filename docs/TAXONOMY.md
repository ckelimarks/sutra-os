# Sutra System Taxonomy

*Defined April 2026. The conceptual model underlying the Sutra app.*

---

## Roles

| Role | Description | Rule |
|------|-------------|------|
| **Sutra** | Master control. Reads, routes, synthesizes. | Never codes. Never gets busy. Talks to workers only. |
| **Worker** | A `claude` CLI instance in an xterm PTY. Ephemeral by default. | One per task. Spawned by Sutra or Christopher. Closed when done. |

Workers are not permanent agents. They're sessions. The context is in the JSONL, not in a running process.

---

## Entity Types

What workers work *on*. Defined by a `CLAUDE.md` in their directory.

| Type | Example | Notes |
|------|---------|-------|
| `product` | LoveNotes | You own it, has users |
| `lab` | Prototypes | Experimental, no external party |
| `client` | Brandywine, BioSync | They pay, you deliver |
| `brand` | Contrarian | External identity, distinct voice — do not cross-pollinate |
| `one-off` | Sifu session | Quick task, no persistent entity, just save and close |

Employer (CF) lives on the work machine. Out of scope for personal-os.

---

## Session Lifecycle

Every worker session has a state:

```
spawn → active → [/fresh or /spoof] → saved → [resume] → active
                                             → [archive] → done
```

| State | What it means | Persistence |
|-------|--------------|-------------|
| **active** | Running PTY, live JSONL being written | `~/.claude/projects/.../uuid.jsonl` |
| **saved** | PTY killed, context intact | JSONL on disk + `.context/sessions/` |
| **spoofed** | Compressed clean narrative | New JSONL via `/spoof`, resumable |
| **archived** | No longer relevant | JSONL kept, not surfaced |

---

## Skills as Templates

Skills are parametric, not project-specific.

```
/status [entity]   →  reads CLAUDE.md + INFRA.md + recent sessions for that entity
/fresh [entity]    →  saves session state to .context/entities/[entity].md
/brief [entity]    →  Sutra reads and synthesizes current state
```

Any entity with the standard interface (`CLAUDE.md` + `INFRA.md`) gets these for free.

---

## Standard Interface (per entity)

```
Projects/[entity]/
  CLAUDE.md          what it is, how to work on it
  INFRA.md           operational state, deployment, gotchas
  context/
    last-session.md  most recent /fresh output
```

---

## What Sutra Does

```
1. Read Atlas (scan Projects/*/CLAUDE.md, filter by active)
2. Read worker reports (summary layer only)
3. Route: decide which entity + which worker model
4. Dispatch: spawn worker with right cwd + context
5. Synthesize: compress reports back to Christopher
6. Manage lifecycle: prompt to save/close idle workers
```

Sutra never reads a worker's raw output. Structured reports and JSONL summaries only.
