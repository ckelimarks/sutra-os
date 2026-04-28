# Voice Client — Upgrade Plan

> Created: 2026-04-19
> Last updated: 2026-04-19
> Status: v2 shipped, v3 planned

## Current State (v2 — shipped)

Full pipeline working:
```
Porcupine wake word → Silero VAD → pre-cached ack → Moonshine STT (~0.2s)
  → persistent Haiku session (stream-json) → RealtimeTTS (SystemEngine, ~0.2s token→audio)
```

**Measured latency (v2):**

| Stage | Time |
|-------|------|
| Silero VAD end-of-speech | ~50ms |
| Moonshine STT | 0.16-0.30s |
| Claude first token | 3.5-5.2s (bottleneck) |
| Token → first audio | 0.16-0.24s |
| **Total (end of speech → first words)** | **~4-5.5s** |
| **Perceived (ack plays immediately)** | **~0.3s** |

**What shipped in v2:**
- [x] Moonshine ONNX STT (replaces Whisper, 6x faster)
- [x] Silero VAD (replaces RMS threshold)
- [x] sounddevice (replaces pyaudio for recording)
- [x] RealtimeTTS + SystemEngine (streaming TTS, 0.2s token→audio)
- [x] All audio through RealtimeTTS (acks, cues, responses — consistent voice)
- [x] Token generator piped directly from Claude stream-json into TTS
- [x] Timing logs on every response
- [x] Persistent Haiku session with voice-optimized system prompt
- [x] Session ID persists to disk across restarts

**What was tried and decided against:**
- PiperEngine via RealtimeTTS: 2.7s first-audio latency (subprocess startup). SystemEngine is 0.35s.
- Direct Piper via temp WAV + afplay: 2-3s synthesis delay per sentence
- Claude interpreter step between STT and LLM: added 4.6s, not useful for clean transcripts
- Interrupt detection via mic monitoring: picks up speaker audio (needs echo cancellation or headphones)

---

## v3 — Two-Brain Architecture (next build)

### The Insight

Claude's first token (~4s) is the bottleneck and we can't speed it up. But we can make the user **not notice** by running a local small LLM in parallel that:
- Speaks intelligent acknowledgments within 80ms
- Answers simple queries directly (~200ms)
- Narrates Claude's tool calls in real-time
- Handles interruptions fluidly

### Architecture

```
You speak
    ↓
Silero VAD → Moonshine STT
    ↓
Qwen 1.5B (local, <100ms)  ──→  speaks immediately via RealtimeTTS
    │
    │ in parallel, routes: "does this need Claude?"
    ↓ if yes
Claude Code CLI (3-5s)      ──→  takes over when ready, Qwen narrates tool calls
```

### What Qwen Does (four jobs)

**1. Intelligent fillers (~80ms)**
Instead of canned "On it." from a WAV bank:
- You: "Build me a dashboard for Mission Match"
- Qwen (instantly): "On it — dashboard for Mission Match, pulling the Recharts setup."

The filler reflects understanding. Massive UX upgrade.

**2. Routing / triage (~100ms)**
Decide: does this need Claude? ~40% of voice queries don't.
- "What time is it?" → Qwen answers directly
- "Cancel that" → Qwen handles
- "Build me a dashboard" → route to Claude
- "How's the weather?" → Qwen + simple tool call

**3. Tool narration (during Claude work)**
Claude emits `tool_use` events in stream-json. Qwen translates them:
- `{tool: "bash", input: "git status"}` → "Checking git real quick..."
- `{tool: "read_file", input: "schema.sql"}` → "Looking at your schema..."
- `{tool: "write_file"}` → "Writing that out now..."

User gets continuous natural narration while Claude does real work.

**4. Interruption handling**
When user interrupts, Qwen acknowledges fluidly ("Yep — switching") while canceling the Claude request.

### Model Choice: Qwen 2.5 1.5B Instruct (Q4_K_M)

- <1GB RAM
- First token <80ms on Apple Silicon
- Reliable structured JSON output (for routing)
- Ships quantized via llama.cpp

### Runtime: llama-server daemon

```bash
llama-server -m qwen2.5-1.5b-instruct-q4_k_m.gguf \
  --port 8080 --ctx-size 2048 --n-gpu-layers 99
```

HTTP POST for each query. Stays warm between requests.

### Three Prompts (all under 200 tokens)

**Acknowledgment:** "You are the voice of an AI assistant. The user just said: `{transcript}`. Respond with a SHORT acknowledgment (under 10 words) that reflects you understood. Never answer the question. Examples: 'Got it, checking now.' 'Pulling that up.' 'On it.'"

**Routing:** "Decide if this needs the full agent (code, files, search, complex reasoning) or if you can handle it (time, small talk, cancellations, yes/no). Output JSON: {route: 'local'|'claude', reason: str}"

**Narration:** "Describe this tool call in 5-8 natural words. Example: `bash: git status` → 'Checking git real quick.'"

### Orchestration

```python
# Mode 1: Instant ack (fire and forget, ~80ms)
ack = qwen.generate(ack_prompt + transcript, max_tokens=25, stream=True)
tts_stream.feed(ack)
tts_stream.play_async()

# Mode 2: Route decision (parallel, ~100ms)
route = qwen.generate(routing_prompt + transcript, max_tokens=50, response_format="json")

# Mode 3: If Claude, narrate tool calls
if route == "claude":
    async for event in claude_stream:
        if event.type == "tool_use":
            narration = qwen.generate(narration_prompt + event.summary, max_tokens=15)
            tts_stream.feed(narration)
        elif event.type == "text":
            tts_stream.feed(event.text)  # Claude takes over
```

### Latency Budget — v3

| Stage | v2 (current) | v3 (two-brain) |
|-------|-------------|----------------|
| First audio | ~0.3s (canned ack) | **~0.08s (intelligent ack)** |
| Simple query answer | 4-5s (Claude) | **~0.2-0.4s (Qwen local)** |
| Complex query answer | 4-5s (Claude) | 4-5s (Claude, with narration) |
| Perceived wait for complex | 4-5s silence | **0.08s ack + narration** |

### Risks & Mitigations

- **Qwen says something wrong:** prompt constrains to acknowledgment only, never factual claims
- **Routing misfires:** bias toward Claude when uncertain; Qwen can hand off mid-sentence
- **Two voices:** same TTS voice, same system prompt style — user can't tell which model speaks
- **Complexity:** phased rollout (see below)

### Implementation Phases

**Phase 1: Intelligent acks (replace canned WAVs)**
- Install llama-server + Qwen 1.5B
- Replace `play_ack()` with Qwen-generated acknowledgment
- Feed Qwen output directly into RealtimeTTS
- No routing, no narration yet

**Phase 2: Routing**
- Add routing prompt
- Simple queries answered by Qwen directly
- Complex queries still go to Claude
- Measure: what % of queries get answered locally?

**Phase 3: Tool narration**
- Parse Claude's stream-json tool_use events
- Feed tool descriptions to Qwen for natural narration
- Speak narration through RealtimeTTS between Claude's text chunks

**Phase 4: Interruption handling**
- Qwen handles the social layer on interrupt
- Cancel signal sent to Claude subprocess
- Graceful handoff

---

## v4 — Interpreter Layer + Sutra UI Integration (needs planning)

The interpreter layer sits between every voice input and every action. This is the architectural decision that determines whether voice feels like a feature or a product.

### Decision: Option 1 (integrated into bridge.py) with Qwen routing

Voice becomes a first-class input channel in the Sutra web UI. Mic icon in chat bar, wake word triggers listening, transcripts and responses appear in the same threads as typed messages. Audio I/O stays server-side (same Mac).

The interpreter (Qwen) routes each voice input to the right path:
- Quick questions → Haiku answers directly (4-5s)
- Agent work → orchestrate dispatch (15-18s)
- System commands → handle locally (instant)

### Open Questions (must answer before building)

1. **Where does the interpreter live?** Inside bridge.py as a service? Its own process? Part of the voice loop? Needs to be stateful (remembers last few turns) but lightweight.

2. **What are the routing categories?** Not just local/Claude. At minimum:
   - "answer directly" (quick facts, conversational)
   - "dispatch to specific agent" (user names the agent)
   - "ask Sutra to orchestrate" (user describes work, Sutra picks the agent)
   - "system command" (cancel, status, repeat, stop speaking)

3. **How does agent targeting work by voice?** "Have WorkerAgent look into X" vs "check LoveNotes" — the interpreter needs to extract agent name + instruction from natural speech. Does Qwen 0.5B handle this or do we need 7B for entity extraction?

4. **What context does the interpreter get?** Options:
   - Just the transcript (simplest)
   - Transcript + agent list with statuses (knows who's online)
   - Transcript + last 3 conversation turns (continuity)
   - Transcript + active tasks from TASKS.md (priority awareness)

5. **How does the response flow back?** Agent dispatch is async and can take 15-60s. Options:
   - Block and wait (bad for long tasks)
   - "Dispatched to WorkerAgent, I'll let you know when it's done" (non-blocking)
   - Narrate tool calls while waiting (v3 Phase 3 — Qwen translates tool_use events)

6. **Error recovery:**
   - Qwen routes to wrong agent → how does user correct?
   - Agent fails mid-dispatch → voice notification?
   - User interrupts mid-dispatch → cancel signal?
   - Ollama is down → full fallback to what?

7. **UI integration specifics:**
   - New WebSocket event types for voice state (listening, transcribing, speaking)
   - Chat bar mic toggle — does it enable wake word or push-to-talk?
   - Voice messages need a visual indicator (mic icon) vs typed messages
   - How to show "dispatched, waiting for agent" state in the thread?

8. **Session architecture:**
   - Voice Haiku session (conversational) vs agent sessions (work) — how do they coexist?
   - Does the voice session see agent responses? Or is it a separate thread?
   - Rolling context: how much history does the interpreter carry?

### Why this needs a full planning session

The interpreter is the coordination layer between human speech, a local LLM, Claude agents, and a web UI. Getting the routing categories wrong means either everything is slow (over-routing to agents) or nothing works (under-routing to Haiku). The async response flow determines whether voice feels like a walkie-talkie or an assistant. This is the kind of architecture that's easy to get 80% right and painful to fix the last 20%.

## Other Ideas (not prioritized)

- **Custom Porcupine wake word** — train "sutra" at console.picovoice.ai
- **Pi 5 port** — config swap for ALSA audio, GPIO push-to-talk
- **Hailo AI HAT+** — accelerated Whisper/Qwen on Pi
- **Voice personality** — warmer Piper voice model fitting Sutra's identity
- **Echo cancellation** — enable interrupt detection without headphones
- **asyncio pipeline** — full async between stages (partially done via RealtimeTTS threading)

## Files

- `server/voice/voice_client.py` — main client
- `server/voice/config.py` — configuration
- `server/voice/start.sh` — launcher
- `data/.voice-session-id` — persistent Haiku session
- `INFRA.md` — voice client section
