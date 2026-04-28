# Sutra UI — Component Glossary

Canonical names for every visible or interactive element. Use these terms when reporting bugs, requesting changes, or writing tasks so we're all speaking the same language.

**Reference design:** `web/mockup-n-warm.html`
**Live implementation:** `web/index.html`

---

## Header (top bar)

| Name | What it is |
|------|-----------|
| **Brand** | "Sutra · orchestrator" label top-left |
| **Attention Pill** | Top-right rounded pill showing "1 needs input · 1 needs approval" with colored status dots |
| **Attention Panel** | Slide-down card that appears when you click the Attention Pill, listing each pending item with Approve/Reject buttons |
| **View Switch** | Timeline / River toggle top-right of the header |

## Toolbar (below header)

| Name | What it is |
|------|-----------|
| **Day Range** | Leftside strip: "Tue · Apr 8 · 9:00 AM — NOW 11:47 AM" |
| **Now Chip** | The glowing "● NOW 11:47 AM" badge |
| **New Agent Button** | Right side, opens the Create Agent modal |
| **Density Slider** | Zoom slider, 50%–800%, labeled "DENSITY" |
| **Snap to Now** | Scrolls the timeline to the current time marker |

## Timeline (the main canvas)

| Name | What it is |
|------|-----------|
| **Ruler** | Top row with time labels and tick marks |
| **Playhead** | The vertical "NOW" line that pulses at the current time |
| **Grid Overlay** | Faint vertical gridlines behind the lanes |
| **Sutra Bus** | Top row with the glowing purple "SUTRA · DISPATCH BUS" — represents Sutra as the source. Clickable → opens full River view |
| **Lane** | One horizontal row per agent (includes label + track) |
| **Lane Label / Track Header** | Left side of a lane — agent name, sub-label (model), icon, swatch, delete button on hover. Sticky when scrolling horizontally. |
| **Context Bar** | Thin bar at the bottom of each Lane Label showing context usage (green/yellow/red) |
| **Lane Track** | The horizontal strip to the right of the label where blocks live |
| **Task Block** | A colored rectangle on a Lane Track representing one task (one user message + its response). Has name, duration, tool subtitle |
| **Active Block** | A Task Block that's currently running — pulses with a glowing ring |
| **Paused Block** | Dashed outline, faded. Waiting on something (usually approval) |
| **Queued Block** | Dashed outline with a clock icon. Waiting in the queue |
| **Tool Subtitle** | Small text inside an active block showing current tool ("Using: Bash") — fed by hooks |
| **Duration Label** | Bottom-right corner of a block showing "12m" or "working for 14s..." |

## Bottom Bar (input area)

| Name | What it is |
|------|-----------|
| **Sutra Chat Input** | Pill-shaped input at the bottom center, labeled "Sutra" with purple glow. Default placeholder: "Talk to Sutra..." |
| **Send Hint** | The "↵" character showing Enter submits |
| **Toast** | Ephemeral notification above the chat input ("Dispatching to Sutra...") |
| **Status Card** | Larger floating card that appears above the chat input when you type "status" — shows all agents + session totals |

## Modals / Overlays

| Name | What it is |
|------|-----------|
| **Task Popup** | Floating card that appears when you click a Task Block. Shows the Vritti (one paragraph summary) above the chat bar |
| **Session Modal** | Full-screen overlay when you click a Lane Label. Shows the agent's full chat thread history |
| **Create Agent Modal** | Form that opens from New Agent button |
| **River View** | Full-screen view showing all agents' messages interleaved chronologically (alternate to Timeline) |

## Compression Terminology (from the PRD)

| Term | What it means |
|------|--------------|
| **Sutra** (layer) | 1-sentence summary of a task outcome (<15 words). Lives on the Task Block face. |
| **Vritti** | 1-paragraph context (50–150 words). Lives in the Task Popup. |
| **Bhashya** | Full detail — the actual message content, tool calls, files. Lives in the Session Modal. |

## States

| Name | What it is |
|------|-----------|
| **Agent Status** | online / busy / idle / offline / error |
| **Task State** | done / active / paused / queued / error |
| **Attention State** | needs_input (red) / needs_permission (amber) / completed (green) / working (blue pulse) |
| **Context State** | fresh (<60%, green) / warn (60–80%, yellow) / crit (80%+, red, pulsing) |

---

## Agent Color Palette (warm)

| CSS variable | Hex | Used for |
|-------------|-----|----------|
| `--c-lovenotes` | `#d16b9e` | rose |
| `--c-content` | `#5a95d6` | sky |
| `--c-geoint` | `#d97e4e` | rust |
| `--c-coder` | `#5db3b3` | teal |
| `--c-brandywine` | `#b8864a` | amber |
| `--c-designer` | `#a78bfa` | violet |
| `--c-helper` | `#6b6b78` | gray (utility) |
| `--sutra` | `#8b5cf6` | purple (Sutra brand) |

Colors cycle by agent index when rendered. Utility agents always use `--c-helper`.

---

*Last updated: 2026-04-11*
