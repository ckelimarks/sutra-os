# Sutra Documentation Consolidation Plan

**Date:** 2026-04-28  
**Status:** PLAN (not yet executed)  
**Author:** Claude  

---

## Executive Summary

This plan consolidates ~30 Sutra documentation files scattered across 3 locations (`Projects/prototypes/sutra/`, `Projects/prototypes/sutra-build/`, downloads/sutra-os/) into a single canonical structure under `Projects/prototypes/sutra-build/docs/`.

**Key finding:** `sutra/` and `sutra-build/` have nearly identical documents (duplicates), while `sutra-build/` is the canonical source with newer content and active development.

---

## File Inventory

### sutra/ directory (9 core docs + session data)

**Project metadata:**
- `CLAUDE.md` — PROJECT INSTRUCTIONS (identical to sutra-build)
- `README.md` — OLD README ("Agent Chat" title, outdated description)

**Specifications & Planning:**
- `SUTRA-PLAN.md` — Implementation plan (Phases 0-4, detailed architecture)
- `SUTRA-BRIEF.md` — One-page executive brief
- `SUTRA-IMPLEMENTATION.md` — Phase-by-phase implementation (same as PHASE-1-PLAN)
- `SUTRA-PRD.md` — Full 890-line PRD (v2.0, all requirements + phasing)
- `Sutra - Handoff.md` — 710-line architectural background (Vedic three-layer model)
- `Sutra PRD — Review, Refinement, JTBD & User Story Mapping.md` — UX-focused PRD variant

**Tactical & Reference:**
- `PHASE-1-PLAN.md` — Detailed Phase 1 with 10 task breakdown (for ralph loop)
- `PROPOSED-SUTRA-PROMPT.md` — System prompt revision proposal
- `PULL-ARCHITECTURE.md` — Pull (zoom) mechanism design
- `TASK.md` — Phase 1 task checklist (10 tasks, mostly unchecked)
- `PROMPT.md` — Agent identity for Phase 1 ralph loop (47 lines)
- `ATLAS.md` — Data model (identical to sutra-build)
- `TAXONOMY.md` — UI terminology reference
- `INFRA.md` — Infrastructure notes

**Session data (non-doc):**
- `data/orchestrator/sessions/*.md` — 3 session logs from 2026-02-18 to 2026-02-20

### sutra-build/ directory (20+ core docs, active source)

**Same as sutra/ but with additions:**
- Everything from `sutra/` PLUS:
  - `API.md` — API endpoint reference
  - `TAXONOMY.md` — UI glossary (confirmed identical to sutra)
  - `SESSION-JSONL-STRUCTURE.md` — Claude Code session format spec (NEW, detailed)
  - `PLAN-session-viewer-integration.md` — UI feature plan (NEW, tactical)
  - `TASK.md` — Extended task checklist with 2026-04-21 progress log (UPDATED)

**In docs/ subdirectory:**
- `ARCHITECTURE.md` (2026-04-28) — **CANONICAL** architectural insight (don't overwrite)
- Mobile/notification fix docs (tactical, not consolidation targets)

---

## Unique Signal Analysis

### What's In sutra/ But Not sutra-build/

**Files to preserve (consolidate):**

1. **PHASE-1-PLAN.md** (416 lines)
   - 10-task breakdown for ralph loop (TASK-1 through TASK-10)
   - Detailed acceptance criteria per task
   - Ralph loop configuration and monitoring
   - **Unique signal:** Concrete task specifications for UI implementation
   - **Consolidation:** Merge into `ROADMAP.md` under "Phase 1 Tasks" section

2. **Sutra - Handoff.md** (710 lines)
   - 7-layer Vedic transmission model (sutra/vritti/bhashya/...)
   - Three synthesis modes (Workshop, War Room, Observatory)
   - Architectural philosophy and design principles
   - **Unique signal:** Foundation for three-layer compression model (appears in SUTRA-PRD but less detailed)
   - **Consolidation:** Keep as `archive/handoff-2026-04.md` with note "Superseded by PRD and ARCHITECTURE. Kept for historical context on Vedic transmission model."

3. **PROPOSED-SUTRA-PROMPT.md** (167 lines)
   - Dual-capability prompt (primary assistant + observer modes)
   - Why Sutra isn't observing adequately
   - Scheduled check-in alternative
   - **Unique signal:** Operational guidance for Sutra's behavior; not in PRD
   - **Consolidation:** Merge into `PRD.md` as "Appendix: Proposed System Prompt (2026-04-08)" with note "Not yet implemented; scheduled check-in alternative documented for future exploration"

4. **PROMPT.md** (47 lines)
   - Ralph loop agent identity (Phase 1 specific)
   - **Unique signal:** None — tactical for Phase 1 ralph, can be archived
   - **Consolidation:** Move to `archive/phase-1-ralph-prompt.md`

5. **PULL-ARCHITECTURE.md** (179 lines)
   - Pull (zoom) mechanism: summary → context → details
   - Synthesis logging with pull_ids
   - Testing checklist
   - **Unique signal:** Implementation details for zoom feature (less detailed in SUTRA-PLAN)
   - **Consolidation:** Merge into `PRD.md` REQ-3.2 and REQ-4.2 sections (already cited in PRD)

### What's In sutra-build/ But Not sutra/

**Files already canonical:**

1. **API.md** — API endpoint reference (live, current)
   - **Consolidation:** Move to `docs/API.md` (already specified, just relocate)

2. **SESSION-JSONL-STRUCTURE.md** (169 lines) — Claude Code session format
   - Entry types, field mapping, tool inputs
   - Context window calculation
   - **Consolidation:** Move to `docs/SESSION-JSONL.md` (as specified)

3. **PLAN-session-viewer-integration.md** (96 lines) — Tactical UI feature plan
   - New API endpoints for session file listing
   - UI integration points (drawer, lane label, post-spoof)
   - **Consolidation:** Move to `docs/ROADMAP.md` under "Phase 3.X: Session Viewer Enhancement" or `archive/session-viewer-plan.md` if post-Phase 3

4. **TASK.md (sutra-build version)** — Extended with 2026-04-21 progress log
   - All Phase 0-5 requirements tracked
   - Detailed progress notes per completed REQ
   - **Consolidation:** Move to `docs/ROADMAP.md` (status section)

### Files Identical Across Both

- `SUTRA-PRD.md` — Full spec (canonical, in sutra-build)
- `SUTRA-BRIEF.md` — Executive brief
- `SUTRA-PLAN.md` — Implementation plan
- `SUTRA-IMPLEMENTATION.md` — Phase breakdown
- `ATLAS.md` — Data model
- `TAXONOMY.md` — Terminology
- `INFRA.md` — Infrastructure
- `CLAUDE.md` — Project instructions
- `README.md` — Project README (different, sutra/ is outdated)

---

## Proposed Final Structure

### `Projects/prototypes/sutra-build/docs/` (canonical)

#### Core Reference
- **PRD.md** (NEW, consolidated)
  - Sources: SUTRA-PRD.md + SUTRA-BRIEF.md + SUTRA-PLAN.md + SUTRA-IMPLEMENTATION.md + "Sutra PRD — Review, Refinement..." + PROPOSED-SUTRA-PROMPT.md (as appendix)
  - Add one-line preamble: "Consolidated from SUTRA-PRD.md, SUTRA-BRIEF.md, SUTRA-PLAN.md, SUTRA-IMPLEMENTATION.md, PROPOSED-SUTRA-PROMPT.md"
  - Includes all 31 requirements with phasing, data model, security model, metrics

- **ROADMAP.md** (NEW, consolidated)
  - Sources: PHASE-1-PLAN.md (10 tasks) + TASK.md (progress log from sutra-build) + PLAN-session-viewer-integration.md (if active) + "What's shipped, what's next, blockers"
  - Add one-line preamble: "Consolidated from PHASE-1-PLAN.md, TASK.md, and tactical feature plans"
  - Sections:
    - "Shipped (Phase 0-2 complete)"
    - "In Progress (Phase 3 active, REQ-3.5-3.7)"
    - "Next (Phase 4-5)"
    - "Phase 1 UI Tasks (for ralph loop)"
    - "Known Blockers"

- **ARCHITECTURE.md** (ALREADY EXISTS, 2026-04-28, DO NOT MODIFY)
  - Top-down vs bottom-up orchestration
  - Why multi-agent democracy test failed
  - Three modes: Workshop, War Room, Observatory
  - Canonical reference for design decisions

- **API.md** (MOVE from root)
  - Endpoint reference (already well-structured)
  - No modifications needed

- **TAXONOMY.md** (MOVE from root)
  - UI terminology and glossary
  - No modifications needed

- **UI-GLOSSARY.md** (MOVE from root)
  - Sutra UI element names and descriptions
  - No modifications needed

- **SESSION-JSONL.md** (NEW, from SESSION-JSONL-STRUCTURE.md)
  - Claude Code session format spec
  - One-line preamble: "Moved from SESSION-JSONL-STRUCTURE.md"

- **INFRA.md** (MOVE from root)
  - Infrastructure state and deployment
  - No modifications needed

#### Reference & Context

- **PULL-ARCHITECTURE.md** (MOVE from sutra/)
  - Zoom mechanism (summary/context/details)
  - Synthesis logging with pull_ids
  - One-line preamble: "Pull (zoom) architecture. See also PRD REQ-3.2 (worker reports) and REQ-4.2 (synthesis logging)"

### `Projects/prototypes/sutra-build/docs/archive/` (historical)

- **handoff-2026-04.md**
  - Source: Sutra - Handoff.md
  - Preamble: "Superseded by PRD.md and ARCHITECTURE.md. Kept for historical context on Vedic transmission model and original three-layer design philosophy."

- **phase-1-ralph-prompt.md**
  - Source: PROMPT.md (Phase 1 identity)
  - Preamble: "Agent identity for Phase 1 ralph loop. Kept for reference; Phase 1 task execution is documented in ROADMAP.md."

- **session-viewer-plan.md** (if deferring feature)
  - Source: PLAN-session-viewer-integration.md
  - Preamble: "Feature plan for session viewer integration. Currently deferred; revisit for Phase 3.5."

### Root Level (DO NOT MOVE, keep for agent context)

- `API.md` → `docs/API.md` (MOVE)
- `INFRA.md` → `docs/INFRA.md` (MOVE)
- `TAXONOMY.md` → `docs/TAXONOMY.md` (MOVE)
- `SESSION-JSONL-STRUCTURE.md` → `docs/SESSION-JSONL.md` (MOVE)
- All others: DELETE after consolidation

---

## Files Ready to Delete

### From `sutra/` (all, since duplicates exist in sutra-build)

After consolidation, the following can be **deleted**:
- SUTRA-PLAN.md
- SUTRA-BRIEF.md
- SUTRA-IMPLEMENTATION.md
- SUTRA-PRD.md
- Sutra - Handoff.md
- Sutra PRD — Review, Refinement, JTBD & User Story Mapping.md
- PHASE-1-PLAN.md
- PROPOSED-SUTRA-PROMPT.md
- PULL-ARCHITECTURE.md
- TASK.md
- PROMPT.md
- ATLAS.md (consolidate to docs)
- TAXONOMY.md (move to docs)
- INFRA.md (move to docs)
- README.md (update in sutra-build)
- CLAUDE.md (keep, project-level)

### From `sutra-build/` root (after moving to docs)

- API.md
- ATLAS.md
- INFRA.md
- TAXONOMY.md
- SESSION-JSONL-STRUCTURE.md
- UI-GLOSSARY.md (if also in docs after this)
- PLAN-session-viewer-integration.md (if no longer active)
- `Sutra - Handoff.md` (after archiving)
- All others except CLAUDE.md (project instructions)

---

## Consolidation Checklist

### Before Execution

- [ ] Review this plan with Christopher for approval
- [ ] Verify ARCHITECTURE.md is final (2026-04-28, don't overwrite)
- [ ] Confirm no external links point to old file locations

### Execution Phase

1. **Create consolidated documents:**
   - [ ] Draft PRD.md (merge 5 sources)
   - [ ] Draft ROADMAP.md (merge 3 sources)
   - [ ] Create SESSION-JSONL.md (rename + move)

2. **Move existing docs to docs/:**
   - [ ] API.md → docs/API.md
   - [ ] INFRA.md → docs/INFRA.md
   - [ ] TAXONOMY.md → docs/TAXONOMY.md
   - [ ] UI-GLOSSARY.md → docs/UI-GLOSSARY.md
   - [ ] PULL-ARCHITECTURE.md → docs/PULL-ARCHITECTURE.md (from sutra/)
   - [ ] ATLAS.md → docs/ATLAS.md

3. **Create archive/ and move outdated docs:**
   - [ ] mkdir -p docs/archive
   - [ ] Sutra - Handoff.md → docs/archive/handoff-2026-04.md (add preamble)
   - [ ] PROMPT.md → docs/archive/phase-1-ralph-prompt.md (add preamble)
   - [ ] PLAN-session-viewer-integration.md → docs/archive/session-viewer-plan.md (if deferring)

4. **Verify structure:**
   - [ ] No broken internal links (search for `SUTRA-PRD`, `PHASE-1-PLAN`, etc. in docs)
   - [ ] All preambles added ("Consolidated from...", "Moved from...", "Superseded by...")
   - [ ] ARCHITECTURE.md unchanged

5. **Cleanup:**
   - [ ] Delete all duplicate docs from sutra/
   - [ ] Delete moved/consolidated docs from sutra-build/ root
   - [ ] Update sutra-build/CLAUDE.md if file references change

6. **Verification:**
   - [ ] `wc -l docs/*.md` — verify all docs exist and have content
   - [ ] `grep -r "Consolidated from\|Moved from" docs/` — verify preambles
   - [ ] Manual check: navigate from PRD → ROADMAP → ARCHITECTURE, no dead links

### Post-Consolidation

- [ ] Update any project bookmarks or external references
- [ ] Commit with message: "docs: consolidate Sutra documentation into canonical structure"
- [ ] Update CLAUDE.md in both sutra/ and sutra-build/ if needed

---

## Signal Preservation Matrix

| Source Doc | Unique Signal | Destination | Preservation Method |
|---|---|---|---|
| SUTRA-PRD.md | 31 requirements, phasing, data model | PRD.md | Direct merge (is base) |
| SUTRA-BRIEF.md | One-page summary | PRD.md (intro) | Merge into overview |
| SUTRA-PLAN.md | Architecture overview | PRD.md | Already cited, consolidate |
| SUTRA-IMPLEMENTATION.md | Phase breakdown | PRD.md | Merge into phasing section |
| PROPOSED-SUTRA-PROMPT.md | System prompt revision | PRD.md (appendix) | Add as "Proposed Prompt A.1" |
| Sutra PRD — Review, Refinement | UX-focused requirements | PRD.md | Merge into relevant REQs |
| Sutra - Handoff.md | Vedic model philosophy | archive/handoff | Preserve with preamble |
| PHASE-1-PLAN.md | 10 task breakdown | ROADMAP.md | Merge into "Phase 1 Tasks" |
| PULL-ARCHITECTURE.md | Zoom mechanism detail | PRD.md + docs/ | Cite in REQ-3.2/4.2, move doc |
| SESSION-JSONL-STRUCTURE.md | Session format spec | SESSION-JSONL.md | Direct move (standalone doc) |
| PLAN-session-viewer-integration.md | Feature plan | ROADMAP.md or archive | Move as tactical plan |
| TASK.md (sutra-build) | Progress log | ROADMAP.md | Merge into status section |
| ATLAS.md | Data model | docs/ATLAS.md | Move, keep as-is |
| TAXONOMY.md | UI terminology | docs/TAXONOMY.md | Move, keep as-is |
| API.md | API reference | docs/API.md | Move, keep as-is |
| INFRA.md | Infrastructure | docs/INFRA.md | Move, keep as-is |
| ARCHITECTURE.md | Design principles | docs/ | DO NOT MODIFY (canonical 2026-04-28) |

**No unique signal lost.** Every document either consolidates into a target or archives with context preserved.

---

## Notes & Caveats

### Cross-referencing

After consolidation, internal links need verification:

**Current patterns that will break:**
- `../SUTRA-PRD.md` → becomes `../docs/PRD.md`
- `./PHASE-1-PLAN.md` → becomes `./docs/ROADMAP.md#phase-1-tasks`
- `PULL-ARCHITECTURE.md` → becomes `docs/PULL-ARCHITECTURE.md`

**Search & update:**
```bash
grep -r "SUTRA-PRD\|PHASE-1-PLAN\|PROPOSED-SUTRA-PROMPT" docs/ --include="*.md"
```

### Debt Items (out of scope)

These are documented but not consolidated (differ by design):

- `sutra/CLAUDE.md` vs `sutra-build/CLAUDE.md` — Keep both (project-level instructions differ)
- `sutra/README.md` vs `sutra-build/README.md` — Keep sutra-build version (sutra/ is outdated)
- Session data (`data/orchestrator/sessions/*.md`) — Not documentation, keep with code

### OSS Sanitization

If `Downloads/sutra-os/` needs updating, apply these consolidated docs **after removing**:
- Internal paths (mangled cwds, absolute paths)
- Proprietary agent names (CF, LoveNotes, GEOINT)
- Internal project references
- Dates and timestamps

Then run sanitization script (see `CLAUDE.md` for `/sanitize-for-oss` skill).

---

## Rollback Plan

If consolidation encounters issues:

1. Revert commit: `git reset --hard HEAD~1`
2. Restore from backup (this CONSOLIDATION-PLAN.md serves as the execution blueprint)
3. Identify blocker and re-plan

No risk: all original files preserved until final cleanup commits.

---

## Timeline

**Execution time:** ~2 hours (one person, sequential)

1. Create consolidated PRD.md — 30 min
2. Create consolidated ROADMAP.md — 30 min
3. Move/create other docs — 30 min
4. Verify structure, fix links — 20 min
5. Delete duplicates, final check — 10 min

**Per-step testing:** ~5 min each (manual navigation, grep checks)

---

**Status:** Plan ready for review and execution approval.

Next step: Present to Christopher for sign-off before executing consolidation.
