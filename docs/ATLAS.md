# Atlas

*Sutra's map of active territories. Read this on init.*

---

## What Atlas Is

Not a file you maintain. A **generated view** of what's currently in play.

**Source of truth:** `Projects/*/CLAUDE.md` — if the file exists, the entity is known.

**Active filter:** cross-referenced against:
- `TASKS.md` P0/P1 items
- Recent git activity per project directory
- Recent `.context/sessions/` files

**Output:** current map of active entities. Different tomorrow if focus shifts.

---

## How to Generate It

```bash
# Known entities — any project with a CLAUDE.md
find ~/project/Projects -name "CLAUDE.md" -maxdepth 3

# Active filter — recent git touches
git log --since="7 days ago" --name-only --pretty=format: | grep "^Projects/" | cut -d/ -f2 | sort -u

# In-flight — recent sessions
ls -t ~/.context/sessions/ | head -10
```

Cross-reference these three. What appears in all three = hot. Two = warm. One = known but dormant.

---

## Current Entities (April 2026)

| Entity | Type | Status | Notes |
|--------|------|--------|-------|
| `lovenotes` | product | active | Blocked on toll-free verification |
| `prototypes` | lab | active | Sutra build in progress |
| `brandywine` | client | warm | Appraisal for Mark pending |
| `biosync` | client | warm | Waiting on Ron follow-up |
| `content` | creative | active | Christopher's voice — essays, Prototype Hour |
| `contrarian` | brand | dormant | No active assignment |
| `job-search` | campaign | archived | CF signed, HG final round pending |

*This table is a snapshot. The generated version is always more current.*

---

## What Atlas Is Not

- Not a list of running agents (that's the worker sidebar)
- Not a task list (that's TASKS.md)
- Not permanent (entities appear when active, fade when dormant)
- Not manually maintained (generated from real signals)

---

## Atlas in the UI

The sidebar in the Sutra app IS the Atlas, expressed as UI.
Short list, reflects NOW. Old sessions don't clutter it.

```
ACTIVE WORKERS
  ● lovenotes     working
  ● prototypes    idle

KNOWN ENTITIES  (resumable)
  ○ brandywine    last session 2d ago
  ○ biosync       last session 5d ago

+ Spawn worker for...
```
