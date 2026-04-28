# a16z Speedrun — Application Draft

**Created:** 2026-04-21
**Deadline:** May 17, 2026
**Source:** Jon Lai (@Tocelot) RFP on X — https://x.com/Tocelot/status/2046608144038768707
**Apply:** https://speedrun.a16z.com/apply

**Status:** Draft — needs Christopher's review + answers to open questions below

---

## Why this fits

Jon Lai's RFP calls for visual GUIs / agent command centers inspired by Factorio and StarCraft. Sutra is literally that — DAW-style timeline view, lane system for multi-agent orchestration, built-in context management. Before seeing the RFP, the codebase already had `TAXONOMY.md` with orchestrator/worker layers and `SUTRA-IDENTITY.md` framing the product as "the thread that reveals patterns across scattered work." Convergent, not reactive.

---

## Fields

### Startup Name
**Sutra**

### One-liner (10 words max)
Candidates (pick one):
- **"Strategy-game UX for orchestrating multiple AI agents"** _(7 words — mirrors Jon Lai's Factorio/StarCraft framing)_
- "Visual command center for multi-agent AI workflows" _(7 words)_
- "The command center for orchestrating Claude Code agents" _(8 words)_

### Startup Description (100 words max)

> Most AI agent tools live in CLIs and chat boxes — paralyzing for anyone outside SV power users. Sutra is a visual command center for multi-agent AI orchestration, inspired by strategy-game UX (Factorio, StarCraft). DAW-style timeline shows agents as lanes, tool calls as blocks. Zoom across parallel workflows, batch-dispatch, manage context, see everything at a glance. Built-in 70%-context auto-compression and spoof-with-steering keep long sessions coherent. Prompt-rewriter, skills library, and hook-driven observability included. Running as a daily-use personal OS — 6,722 Claude Code sessions of real load, 9 specialized agents, production-grade context management. Opening for teams hitting the scaling wall.

_(~95 words)_

### Team Description (100 words max)

> Solo founder today, actively recruiting a technical cofounder. Christopher is both the builder and the power user — 6,722 Claude Code sessions of real daily use iterating on Sutra while shipping LoveNotes (couples app, SMS + AI) and publishing the Human Interface Thesis (3 of 4 essays live). Background: taught 315 students, shipped consumer AI products, final-round interviews at Healthy Gamer and Devoted Health. The best first user is the builder who's already used the product 6,722 times. Advisor conversations in progress with AI product leaders and prior founders in the agent infrastructure space.

_(~95 words)_

### Primary Category
**Infrastructure / Dev Tools**

### Secondary Category
**Consumer Applications**
_(Rationale: the RFP frames this as "Windows for agents" / mass-market accessibility — dev tools now, consumer later)_

### Location
- **Country:** United States
- **City:** Austin, TX

### Founded — DECISION NEEDED
- **2025-Q1** if agent-chat predecessor counts (longer runway of work)
- **2026-04** if only the named sutra-build product counts (honest about current crystallization)
- Suggested: **2025-05** if agent-chat first meaningful commits land there. Check with `git log --reverse | head` in sutra-build and agent-chat.

### Website — DECISION NEEDED
Options:
- sutra.christopherkmarks.com (if exists)
- christopherkmarks.com (personal)
- Leave blank (field is optional)

### Anything else we should know? (100 words max)

> Before I saw Jon Lai's RFP, my codebase already had a TAXONOMY.md distinguishing orchestrator/worker layers and an identity file framing Sutra as "the thread that reveals patterns across scattered work." The strategy-game analogy wasn't imported — it was convergent. I'm pitching a working system with an N=1 user base of one deeply committed daily user, 6,722 sessions of real production use, and a public thesis (Human Interface Thesis) on the human+AI symbiosis this interface is designed around. Demo available on request. Full repo and session corpus open for review.

_(~85 words)_

### Where did you learn about Speedrun?
- **Source:** X (Twitter)
- **Additional info:** @Tocelot (Jon Lai) RFP post on visual agent GUIs / Factorio-inspired orchestration — https://x.com/Tocelot/status/2046608144038768707

---

## Open Questions Before Submitting

1. **Founded date** — 2025-Q1 (agent-chat origin) or 2026-04 (sutra-build crystallization)?
2. **Website** — do you have one for Sutra specifically, or use personal?
3. **Named advisors** — any specific names to add to Team Description? If not, "advisor conversations in progress" works but is soft.
4. **Cofounder recruiting** — is this truly active? If not, reframe as "solo, open to the right cofounder if mission aligns."
5. **Demo video** — record a 1-minute walkthrough before submitting? (timeline view + dispatch to 2 agents + reset modal + improve-prompt). Makes the application significantly stronger.

---

## Optional Sections to Fill (from form)

- **Pitch Deck (PDF)** — not required, but strong signal. Could pull from existing Sutra docs (SUTRA-BRIEF.md, ATLAS.md) into a 10-slide deck.
- **Traction** — 6,722 sessions, 9 agents running, real self-use load. Frame as "product-market fit with N=1 committed user before any outside traction."
- **Funding History** — likely blank (pre-seed).
- **Active Fundraising Round** — probably blank.
- **Referral** — Jon Lai himself if there's any way to frame that; otherwise leave blank.

---

## Prep Checklist

- [ ] Finalize founded date, website, team description specifics
- [ ] Record 1-min demo video (timeline + dispatch + reset modal + improve-prompt)
- [ ] Consider pulling together a pitch deck from SUTRA-BRIEF + ATLAS + screenshots
- [ ] Reddit post the RFP discussion (draft already written) for visibility
- [ ] Submit by **May 17, 2026**

---

## Positioning Notes

- Lead with the **convergence**, not the response. "I was already building this. The RFP confirms the market read."
- **Personal usage depth** is the moat. Anyone can mock up an agent GUI. Very few have 6,722 sessions of real use driving every design decision.
- **Context management** is the technical differentiator. Auto-spoof at 70%, turn-based reset, three injection points, event-based observability. None of that is obvious from the outside — all of it emerged from pain.
- **Human + AI symbiosis** is the philosophical frame. Published thesis. This isn't an agent automation play — it's about the interface layer between human will and model capability.
