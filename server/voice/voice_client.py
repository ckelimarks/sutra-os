"""
Sutra Voice Client v2.
Wake word → Silero VAD → instant ack → Moonshine STT → streaming Haiku → say TTS

v2 upgrades over v1:
- Moonshine ONNX STT (~55ms vs Whisper's 1.2s)
- Silero VAD for proper end-of-speech detection (replaces RMS threshold)
- sounddevice replaces pyaudio (cleaner, no portaudio compile)
- Pre-cached ack WAVs for instant feedback

Usage:
    python3 -m server.voice.voice_client                       # full voice mode
    python3 -m server.voice.voice_client --keyboard-only       # text input mode
    python3 -m server.voice.voice_client --orchestrator        # route through Sutra server
    python3 -m server.voice.voice_client --stt whisper         # fallback to Whisper
"""

import io
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Optional

import numpy as np
import requests
import sounddevice as sd
import torch

from .config import VoiceConfig

# Optional dependencies
try:
    import pvporcupine
    HAS_PORCUPINE = True
except ImportError:
    HAS_PORCUPINE = False

try:
    from moonshine_onnx import MoonshineOnnxModel, load_tokenizer as load_moonshine_tokenizer
    HAS_MOONSHINE = True
except ImportError:
    HAS_MOONSHINE = False

try:
    from silero_vad import load_silero_vad
    HAS_SILERO = True
except ImportError:
    HAS_SILERO = False

try:
    import whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    from RealtimeTTS import TextToAudioStream, PiperEngine, PiperVoice
    HAS_REALTIMETTS = True
except ImportError:
    HAS_REALTIMETTS = False


# ============================================================================
# Model singletons (lazy-loaded)
# ============================================================================

_moonshine_model = None
_moonshine_tokenizer = None
_whisper_model = None
_silero_model = None
_tts_stream = None
_qwen_client = None


def get_moonshine():
    global _moonshine_model, _moonshine_tokenizer
    if _moonshine_model is None:
        print("  Loading Moonshine STT...", end="", flush=True)
        _moonshine_model = MoonshineOnnxModel(model_name="moonshine/base")
        _moonshine_tokenizer = load_moonshine_tokenizer()
        print(" ready.")
    return _moonshine_model, _moonshine_tokenizer


def get_whisper(model_name: str = "base"):
    global _whisper_model
    if _whisper_model is None:
        print(f"  Loading Whisper '{model_name}'...", end="", flush=True)
        _whisper_model = whisper.load_model(model_name)
        print(" ready.")
    return _whisper_model


def get_silero():
    global _silero_model
    if _silero_model is None:
        print("  Loading Silero VAD...", end="", flush=True)
        _silero_model = load_silero_vad(onnx=True)
        print(" ready.")
    return _silero_model


def get_qwen():
    """Initialize Qwen client if llama-server is running."""
    global _qwen_client
    if _qwen_client is None:
        from .qwen import QwenClient
        client = QwenClient()
        if client.is_available():
            print("  Qwen (llama-server): connected.")
            _qwen_client = client
        else:
            print("  Qwen (llama-server): not running, using canned acks.")
    return _qwen_client


def get_tts_stream(config: VoiceConfig):
    """Initialize RealtimeTTS stream. Reused across calls."""
    global _tts_stream
    if _tts_stream is None and HAS_REALTIMETTS:
        if config.tts_engine == "piper":
            # Use SystemEngine — piper quality but via RealtimeTTS streaming
            # (PiperEngine has 2.7s startup latency, SystemEngine is 0.35s)
            try:
                from RealtimeTTS import SystemEngine
                print("  Loading RealtimeTTS (SystemEngine)...", end="", flush=True)
                engine = SystemEngine()
                _tts_stream = TextToAudioStream(engine)
                print(" ready.")
            except ImportError:
                # Fallback to PiperEngine
                import shutil
                piper_path = shutil.which("piper")
                model_path = os.path.expanduser(config.piper_model)
                if piper_path and Path(model_path).exists():
                    print("  Loading RealtimeTTS (Piper)...", end="", flush=True)
                    voice = PiperVoice(model_file=model_path)
                    engine = PiperEngine(piper_path=piper_path, voice=voice)
                    _tts_stream = TextToAudioStream(engine)
                    print(" ready.")
    return _tts_stream


# ============================================================================
# Pure functions
# ============================================================================

def check_dependencies() -> dict:
    return {
        "pvporcupine": HAS_PORCUPINE,
        "moonshine": HAS_MOONSHINE,
        "whisper": HAS_WHISPER,
        "silero_vad": HAS_SILERO,
        "sounddevice": True,
        "realtimetts": HAS_REALTIMETTS,
        "claude": subprocess.run(["which", "claude"], capture_output=True).returncode == 0,
        "piper": bool(subprocess.run(["which", "piper"], capture_output=True).returncode == 0),
        "say": sys.platform == "darwin",
    }


HALLUCINATION_PATTERNS = {
    "thank you.", "thanks for watching.", "thanks for listening.",
    "please subscribe.", "like and subscribe.",
    "...", "you", "bye.", "the end.",
}


def filter_hallucinations(text: str) -> Optional[str]:
    cleaned = text.strip()
    if not cleaned or len(cleaned) < 3:
        return None
    if cleaned.lower() in HALLUCINATION_PATTERNS:
        return None
    if all(c in "♪♫♬🎵🎶 " for c in cleaned):
        return None
    return cleaned


# ============================================================================
# Pre-cached acknowledgment WAVs
# ============================================================================

ACKNOWLEDGMENTS = [
    "On it.",
    "Let me think.",
    "One moment.",
    "Working on it.",
    "Heard you.",
    "Thinking.",
]

_ack_wavs: list[str] = []
_ack_index = 0


def precache_acknowledgments(piper_model: str) -> None:
    global _ack_wavs
    model_path = os.path.expanduser(piper_model)
    use_piper = Path(model_path).exists()

    cache_dir = Path(tempfile.gettempdir()) / "sutra-voice-acks"
    cache_dir.mkdir(exist_ok=True)

    print("  Pre-caching acks...", end="", flush=True)
    for i, phrase in enumerate(ACKNOWLEDGMENTS):
        wav_path = cache_dir / f"ack_{i}.wav"
        if wav_path.exists():
            _ack_wavs.append(str(wav_path))
            continue

        if use_piper:
            proc = subprocess.Popen(
                ["piper", "--model", model_path, "--output_raw"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            )
            raw, _ = proc.communicate(input=phrase.encode())
            wav_bytes = pcm_to_wav(raw, 22050)
            wav_path.write_bytes(wav_bytes)
        else:
            wav_path.write_text(phrase)

        _ack_wavs.append(str(wav_path))
    print(" done.")


def play_ack(transcript: str = None) -> None:
    """Play an acknowledgment. Uses Qwen for intelligent ack if available."""
    global _ack_index

    # Try Qwen closed-class ack selection
    if _qwen_client and transcript and _tts_stream:
        from .qwen import acknowledge, ACKS
        system_prompt = acknowledge(transcript)
        raw = _qwen_client.generate(transcript, system=system_prompt, max_tokens=3)
        # Parse digit from response
        digits = [c for c in raw if c.isdigit()]
        if digits:
            idx = int(digits[0]) - 1
            if 0 <= idx < len(ACKS):
                ack_text = ACKS[idx]
                print(f"  [Qwen ack]: {ack_text}")
                _tts_stream.feed(ack_text)
                _tts_stream.play(
                    fast_sentence_fragment=True,
                    buffer_threshold_seconds=0.0,
                    minimum_sentence_length=1,
                    minimum_first_fragment_length=1,
                )
                return

    # Fallback: canned ack via RealtimeTTS or WAV
    idx = _ack_index % len(ACKNOWLEDGMENTS)
    _ack_index += 1

    if _tts_stream:
        _tts_stream.feed(ACKNOWLEDGMENTS[idx])
        _tts_stream.play(
            fast_sentence_fragment=True,
            buffer_threshold_seconds=0.0,
            minimum_sentence_length=1,
            minimum_first_fragment_length=1,
        )
    elif _ack_wavs:
        path = _ack_wavs[idx]
        if path.endswith(".wav") and os.path.getsize(path) > 100:
            subprocess.run(["afplay", path], check=False)
        else:
            text = Path(path).read_text().strip()
            subprocess.run(["say", "-v", "Samantha", text], check=False)


def play_ack_async(transcript: str = None) -> threading.Thread:
    t = threading.Thread(target=play_ack, args=(transcript,), daemon=True)
    t.start()
    return t


# ============================================================================
# Response cleaning
# ============================================================================

def clean_for_speech(text: str) -> str:
    s = text
    s = re.sub(r'```[\s\S]*?```', '', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)
    s = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', s)
    s = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', s)
    s = re.sub(r'^#{1,6}\s+', '', s, flags=re.MULTILINE)
    s = re.sub(r'^\s*[-*+]\s+', '', s, flags=re.MULTILINE)
    s = re.sub(r'^\s*\d+\.\s+', '', s, flags=re.MULTILINE)
    s = re.sub(r'https?://\S+', '', s)
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s)
    s = re.sub(r'[→←↑↓|~^<>{}[\]\\]', ' ', s)
    s = re.sub(r'\n{2,}', '. ', s)
    s = re.sub(r'\n', ' ', s)
    s = re.sub(r'\s{2,}', ' ', s)
    return s.strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    merged = []
    for p in parts:
        if merged and len(p) < 15:
            merged[-1] += " " + p
        else:
            merged.append(p)
    return [s for s in merged if s.strip()]


# ============================================================================
# Audio I/O via sounddevice
# ============================================================================

def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def record_with_vad(
    max_duration: float = 10.0,
    sample_rate: int = 16000,
) -> np.ndarray:
    """Record audio using Silero VAD for end-of-speech detection.

    Returns float32 numpy array at 16kHz.
    """
    vad = get_silero()
    chunk_ms = 32  # Silero works on 32ms chunks at 16kHz
    chunk_samples = int(sample_rate * chunk_ms / 1000)
    max_chunks = int(max_duration * 1000 / chunk_ms)

    frames = []
    speech_started = False
    silence_after_speech = 0
    # ~0.5s of silence after speech = done (16 chunks * 32ms)
    silence_threshold_chunks = 16

    print("  Speak now...", end="", flush=True)

    # Record in chunks using sounddevice blocking read
    stream = sd.InputStream(samplerate=sample_rate, channels=1, dtype='float32',
                            blocksize=chunk_samples)
    stream.start()

    try:
        for _ in range(max_chunks):
            chunk, _ = stream.read(chunk_samples)
            chunk_1d = chunk[:, 0]  # mono
            frames.append(chunk_1d.copy())

            # Run VAD on this chunk
            chunk_tensor = torch.from_numpy(chunk_1d)
            speech_prob = vad(chunk_tensor, sample_rate).item()

            if speech_prob > 0.5:
                speech_started = True
                silence_after_speech = 0
            elif speech_started:
                silence_after_speech += 1
                if silence_after_speech >= silence_threshold_chunks:
                    break
    finally:
        stream.stop()
        stream.close()

    audio = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
    elapsed = len(audio) / sample_rate
    print(f" ({elapsed:.1f}s)")
    return audio


def record_with_rms(
    max_duration: float = 10.0,
    sample_rate: int = 16000,
    silence_threshold: float = 0.01,
    silence_duration: float = 0.8,
) -> np.ndarray:
    """Fallback recording with RMS silence detection (no Silero)."""
    chunk_samples = 1024
    max_chunks = int(max_duration * sample_rate / chunk_samples)
    chunks_for_silence = int(silence_duration * sample_rate / chunk_samples)

    frames = []
    speech_started = False
    silent_chunks = 0

    print("  Speak now...", end="", flush=True)
    stream = sd.InputStream(samplerate=sample_rate, channels=1, dtype='float32',
                            blocksize=chunk_samples)
    stream.start()

    try:
        for _ in range(max_chunks):
            chunk, _ = stream.read(chunk_samples)
            chunk_1d = chunk[:, 0]
            frames.append(chunk_1d.copy())

            rms = np.sqrt(np.mean(chunk_1d ** 2))
            if rms > silence_threshold:
                speech_started = True
                silent_chunks = 0
            else:
                silent_chunks += 1

            if speech_started and silent_chunks >= chunks_for_silence:
                break
    finally:
        stream.stop()
        stream.close()

    audio = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
    elapsed = len(audio) / sample_rate
    print(f" ({elapsed:.1f}s)")
    return audio


# ============================================================================
# STT — Moonshine (fast) or Whisper (fallback)
# ============================================================================

def transcribe_moonshine(audio: np.ndarray) -> str:
    """Transcribe with Moonshine ONNX. ~55ms for 3s audio."""
    model, tokenizer = get_moonshine()
    audio_2d = audio.reshape(1, -1).astype(np.float32)
    tokens = model.generate(audio_2d)
    text = tokenizer.decode_batch(tokens)[0]
    return text


def transcribe_whisper(audio: np.ndarray, model_name: str = "base") -> str:
    """Transcribe with local Whisper. ~1.2s for 3s audio."""
    model = get_whisper(model_name)
    # Whisper expects float32 numpy array
    result = model.transcribe(audio, fp16=False)
    return result["text"]


def transcribe(audio: np.ndarray, stt_backend: str = "moonshine", whisper_model: str = "base") -> str:
    """Dispatch to the right STT backend."""
    if stt_backend == "moonshine" and HAS_MOONSHINE:
        return transcribe_moonshine(audio)
    elif HAS_WHISPER:
        return transcribe_whisper(audio, whisper_model)
    else:
        return "(no STT backend available)"


# ============================================================================
# TTS
# ============================================================================

def speak_with_say(text: str, voice: str = "Samantha") -> None:
    subprocess.run(["say", "-v", voice, "-r", "195", text], check=False)


def speak_quick(text: str, config: VoiceConfig) -> None:
    """Speak a short phrase — uses RealtimeTTS if available, else say."""
    if _tts_stream:
        _tts_stream.feed(text)
        _tts_stream.play(
            fast_sentence_fragment=True,
            buffer_threshold_seconds=0.0,
            minimum_sentence_length=1,
            minimum_first_fragment_length=1,
        )
    else:
        speak_with_say(text, config.say_voice)


def speak_with_piper(text: str, model_path: str) -> None:
    """Piper TTS — better quality, higher latency."""
    model_path = os.path.expanduser(model_path)
    if not Path(model_path).exists():
        speak_with_say(text)
        return
    proc = subprocess.Popen(
        ["piper", "--model", model_path, "--output_raw"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    raw, _ = proc.communicate(input=text.encode())
    wav = pcm_to_wav(raw, 22050)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav)
        subprocess.run(["afplay", f.name], check=False)
        os.unlink(f.name)


def speak_sentence(text: str, config: VoiceConfig) -> None:
    if config.tts_engine == "piper" and _tts_stream:
        _tts_stream.feed(text)
        _tts_stream.play(
            fast_sentence_fragment=True,
            buffer_threshold_seconds=0.0,
            minimum_sentence_length=1,
        )
    elif config.tts_engine == "piper":
        speak_with_piper(text, config.piper_model)
    else:
        speak_with_say(text, config.say_voice)


def speak_response(text: str, config: VoiceConfig) -> None:
    cleaned = clean_for_speech(text)
    if cleaned:
        speak_sentence(cleaned, config)


# ============================================================================
# Persistent Haiku session
# ============================================================================

VOICE_SYSTEM_PROMPT = (
    "You are Sutra, a voice assistant. Rules for ALL responses:\n"
    "- Respond in 1-3 short spoken sentences. Be concise.\n"
    "- Never use markdown: no asterisks, no bullet points, no headers, no backticks, no code blocks.\n"
    "- Never include URLs in your response.\n"
    "- Write as if speaking aloud. Use natural conversational English.\n"
    "- No numbered lists. If listing things, use 'first, second, third' in prose.\n"
    "- You have your project's context via CLAUDE.md.\n"
)

_haiku_session_id: Optional[str] = None
SESSION_FILE = Path(__file__).resolve().parent.parent.parent / "data" / ".voice-session-id"


def _save_session_id(sid: str) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(sid)


def _load_session_id() -> Optional[str]:
    if SESSION_FILE.exists():
        sid = SESSION_FILE.read_text().strip()
        return sid if sid else None
    return None


def init_haiku_session(cwd: str) -> str:
    global _haiku_session_id

    existing = _load_session_id()
    if existing:
        print(f"  Resuming Haiku ({existing[:8]}...)...", end="", flush=True)
        result = subprocess.run(
            ["claude", "--print", "--model", "haiku", "--resume", existing,
             "--output-format", "json", "-p", "ping"],
            capture_output=True, text=True, timeout=15, cwd=cwd,
        )
        if result.returncode == 0 and result.stdout.strip():
            _haiku_session_id = existing
            print(" ready.")
            return _haiku_session_id
        else:
            print(" stale.")

    print("  Starting Haiku...", end="", flush=True)
    result = subprocess.run(
        ["claude", "--print", "--output-format", "json", "--model", "haiku",
         "-p", VOICE_SYSTEM_PROMPT],
        capture_output=True, text=True, timeout=30, cwd=cwd,
    )

    try:
        data = json.loads(result.stdout)
        _haiku_session_id = data.get("session_id")
    except (json.JSONDecodeError, KeyError):
        _haiku_session_id = None

    if _haiku_session_id:
        _save_session_id(_haiku_session_id)
        print(f" ready ({_haiku_session_id[:8]}...)")
    else:
        print(" ready (stateless)")

    return _haiku_session_id


def _haiku_token_generator(instruction: str, cwd: str):
    """Generator that yields text tokens from Claude stream-json.

    Used to pipe directly into RealtimeTTS for true end-to-end streaming.
    """
    global _haiku_session_id

    cmd = ["claude", "--print", "--verbose", "--model", "haiku", "--output-format", "stream-json"]
    if _haiku_session_id:
        cmd.extend(["--resume", _haiku_session_id])
    cmd.extend(["-p", instruction])

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, cwd=cwd)
    except FileNotFoundError:
        yield "Claude CLI not found."
        return

    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            yield text

            elif event.get("type") == "result":
                # result has final text but we've already yielded from assistant events
                break

        proc.wait(timeout=5)
    except Exception as e:
        print(f"  (stream error: {e})")
        proc.terminate()


def ask_haiku_streaming(instruction: str, cwd: str, config: VoiceConfig) -> str:
    """Stream Haiku response. Pipes tokens directly into TTS as they arrive."""
    t_start = time.time()
    t_first_token = None
    t_first_audio = None
    full_response_parts = []

    if config.tts_engine == "piper" and _tts_stream:
        # True end-to-end streaming: Claude tokens → RealtimeTTS → speaker
        # RealtimeTTS handles sentence fragmentation and audio output

        def on_audio_start():
            nonlocal t_first_audio
            if t_first_audio is None:
                t_first_audio = time.time()

        _tts_stream.on_audio_stream_start = on_audio_start

        def token_generator():
            nonlocal t_first_token
            for token in _haiku_token_generator(instruction, cwd):
                if t_first_token is None:
                    t_first_token = time.time()
                # Clean markdown as tokens arrive
                cleaned = clean_for_speech(token)
                if cleaned:
                    full_response_parts.append(cleaned)
                    yield cleaned

        # Feed generator directly — RealtimeTTS pulls tokens as needed
        _tts_stream.feed(token_generator())
        # play_async returns immediately, audio plays in background
        _tts_stream.play_async(
            fast_sentence_fragment=True,
            buffer_threshold_seconds=0.0,
            minimum_sentence_length=1,
            minimum_first_fragment_length=1,
        )

        # Wait for playback to finish
        while _tts_stream.is_playing():
            time.sleep(0.05)

        t_done = time.time()
        full_text = "".join(full_response_parts)
        if full_text:
            print(f"  Sutra: {full_text}")

        ft = (t_first_token - t_start) if t_first_token else 0
        fa = (t_first_audio - t_start) if t_first_audio else 0
        print(f"  [Timing] first_token={ft:.2f}s  first_audio={fa:.2f}s  total={t_done - t_start:.2f}s  tts=piper-stream")
        return full_text or "I didn't catch that."

    else:
        # say: collect response then speak
        full_response = ""
        for token in _haiku_token_generator(instruction, cwd):
            if t_first_token is None:
                t_first_token = time.time()
            full_response += token

        if not full_response:
            return "I didn't catch that."

        cleaned = clean_for_speech(full_response)
        if cleaned:
            print(f"  Sutra: {cleaned}")
            t_first_audio = time.time()
            sentences = split_sentences(cleaned)
            for s in sentences:
                speak_sentence(s, config)

        t_done = time.time()
        ft = (t_first_token - t_start) if t_first_token else 0
        fa = (t_first_audio - t_start) if t_first_audio else 0
        print(f"  [Timing] first_token={ft:.2f}s  first_audio={fa:.2f}s  total={t_done - t_start:.2f}s  tts=say")
        return full_response


def ask_haiku(instruction: str, cwd: str) -> str:
    """Non-streaming fallback."""
    global _haiku_session_id
    cmd = ["claude", "--print", "--model", "haiku"]
    if _haiku_session_id:
        cmd.extend(["--resume", _haiku_session_id])
    cmd.extend(["-p", instruction])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)
        return result.stdout.strip() or "I didn't catch that."
    except subprocess.TimeoutExpired:
        return "Timed out."
    except FileNotFoundError:
        return "Claude CLI not found."


def send_to_orchestrator(instruction: str, agent: str, url: str) -> dict:
    try:
        resp = requests.post(url, json={"agent": agent, "instruction": instruction, "priority": "normal"}, timeout=300)
        if not resp.text:
            return {"status": "error", "response": f"Empty response from '{agent}'"}
        return resp.json()
    except requests.ConnectionError:
        return {"status": "error", "response": "Orchestrator not running."}
    except Exception as e:
        return {"status": "error", "response": str(e)}


# ============================================================================
# Main loops
# ============================================================================

def run_keyboard_loop(config: VoiceConfig) -> None:
    cwd = config.project_cwd
    print(f"\nSutra Voice Client v2 (keyboard)")
    print(f"  Session: Persistent Haiku")
    print(f"  Type 'quit' to exit\n")
    init_haiku_session(cwd)

    while True:
        try:
            text = input("[Sutra] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not text or text.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        t0 = time.time()
        response_text = ask_haiku(text, cwd)
        cleaned = clean_for_speech(response_text)
        print(f"  ({time.time()-t0:.1f}s) {cleaned}\n")

        if config.tts_engine != "none":
            speak_response(cleaned, config)


def run_voice_loop(config: VoiceConfig) -> None:
    """Main voice loop: wake word → VAD record → ack → STT → Haiku → TTS."""
    deps = check_dependencies()
    cwd = config.project_cwd
    use_vad = HAS_SILERO
    stt_name = "Moonshine" if config.stt_backend == "moonshine" and HAS_MOONSHINE else "Whisper"

    print(f"\nSutra Voice Client v2")
    print(f"  Wake word: '{config.wake_word}'")
    print(f"  VAD: {'Silero' if use_vad else 'RMS fallback'}")
    print(f"  STT: {stt_name}")
    print(f"  LLM: Persistent Haiku (streaming)")
    tts_label = f"RealtimeTTS streaming" if config.tts_engine == "piper" and HAS_REALTIMETTS else f"macOS say ({config.say_voice})"
    print(f"  TTS: {tts_label}")

    # Pre-load all models at startup
    if config.stt_backend == "moonshine" and HAS_MOONSHINE:
        get_moonshine()
    elif HAS_WHISPER:
        get_whisper(config.whisper_model)
    if use_vad:
        get_silero()
    if config.tts_engine == "piper":
        get_tts_stream(config)
    get_qwen()
    precache_acknowledgments(config.piper_model)
    init_haiku_session(cwd)

    # Init Porcupine
    porcupine = None
    if HAS_PORCUPINE and config.porcupine_key:
        try:
            porcupine = pvporcupine.create(
                access_key=config.porcupine_key,
                keywords=[config.wake_word],
            )
            print(f"  Wake word: Porcupine")
        except Exception as e:
            print(f"  Porcupine failed: {e}")

    print(f"\n  {'Listening...' if porcupine else 'Press Enter to speak...'}\n")

    # Wake word needs pyaudio for Porcupine (sounddevice doesn't work with Porcupine's frame format)
    import pyaudio
    pa = pyaudio.PyAudio()

    try:
        while True:
            # --- Wait for wake word ---
            if porcupine:
                ww_stream = pa.open(
                    rate=porcupine.sample_rate, channels=1,
                    format=pyaudio.paInt16, input=True,
                    frames_per_buffer=porcupine.frame_length,
                )
                while True:
                    pcm = ww_stream.read(porcupine.frame_length, exception_on_overflow=False)
                    pcm_unpacked = struct.unpack_from("h" * porcupine.frame_length, pcm)
                    if porcupine.process(pcm_unpacked) >= 0:
                        break
                ww_stream.stop_stream()
                ww_stream.close()
            else:
                try:
                    input("  Press Enter to speak...")
                except EOFError:
                    break

            # --- "Listening" cue ---
            speak_quick("Listening.", config)

            # --- Record with VAD or RMS ---
            if use_vad:
                audio = record_with_vad(config.max_record_duration, config.sample_rate)
            else:
                audio = record_with_rms(config.max_record_duration, config.sample_rate)

            # --- STT first (Moonshine is fast ~0.2s) ---
            t0 = time.time()
            transcript = transcribe(audio, config.stt_backend, config.whisper_model)
            stt_time = time.time() - t0
            print(f"  Heard: \"{transcript.strip()}\" ({stt_time:.3f}s)")

            cleaned = filter_hallucinations(transcript)
            if not cleaned:
                print("  (silence, back to listening)\n")
                continue

            # --- Intelligent ack with transcript (non-blocking) ---
            ack_thread = play_ack_async(cleaned)
            ack_thread.join()

            # --- LLM response (streaming) ---
            t0 = time.time()
            if config.orchestrator_mode:
                result = send_to_orchestrator(cleaned, config.default_agent, config.orchestrator_url)
                response_text = result.get("response", result.get("message", "No response"))
                response_text = clean_for_speech(response_text)
                print(f"  Sutra ({time.time()-t0:.1f}s): {response_text}")
                speak_response(response_text, config)
            else:
                response_text = ask_haiku_streaming(cleaned, cwd, config)
                print(f"  ({time.time()-t0:.1f}s total)")

            # --- Follow-up window ---
            follow_up_start = time.time()
            while time.time() - follow_up_start < config.listen_timeout:
                print("  (follow-up...)")
                speak_quick("Go ahead.", config)

                if use_vad:
                    audio = record_with_vad(config.max_record_duration, config.sample_rate)
                else:
                    audio = record_with_rms(config.max_record_duration, config.sample_rate)

                transcript = transcribe(audio, config.stt_backend, config.whisper_model)
                cleaned = filter_hallucinations(transcript)

                if not cleaned:
                    break

                print(f"  Heard: \"{cleaned}\"")
                ack_thread = play_ack_async(cleaned)

                if config.orchestrator_mode:
                    result = send_to_orchestrator(cleaned, config.default_agent, config.orchestrator_url)
                    response_text = result.get("response", "No response")
                    ack_thread.join()
                    response_text = clean_for_speech(response_text)
                    print(f"  Sutra: {response_text}")
                    speak_response(response_text, config)
                else:
                    ack_thread.join()
                    response_text = ask_haiku_streaming(cleaned, cwd, config)

                follow_up_start = time.time()

            print(f"\n  {'Listening...' if porcupine else 'Press Enter to speak...'}\n")

    except KeyboardInterrupt:
        print("\nGoodbye.")
    finally:
        pa.terminate()
        if porcupine:
            porcupine.delete()


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sutra Voice Client v2")
    parser.add_argument("--keyboard-only", action="store_true", help="Text input mode")
    parser.add_argument("--orchestrator", action="store_true", help="Route through Sutra orchestrator")
    parser.add_argument("--agent", default=None, help="Agent for orchestrator mode")
    parser.add_argument("--tts", default=None, choices=["say", "piper", "none"], help="TTS engine")
    parser.add_argument("--stt", default=None, choices=["moonshine", "whisper"], help="STT backend")
    parser.add_argument("--whisper-model", default=None,
                        choices=["tiny", "base", "small", "medium", "large"],
                        help="Whisper model size (if using whisper)")
    args = parser.parse_args()

    config = VoiceConfig.from_env()
    if args.orchestrator:
        config.orchestrator_mode = True
    if args.agent:
        config.default_agent = args.agent
    if args.tts:
        config.tts_engine = args.tts
    if args.stt:
        config.stt_backend = args.stt
    if args.whisper_model:
        config.whisper_model = args.whisper_model

    if args.keyboard_only:
        run_keyboard_loop(config)
    else:
        run_voice_loop(config)
