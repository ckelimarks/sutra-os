"""Voice client configuration."""

import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


@dataclass
class VoiceConfig:
    porcupine_key: Optional[str] = None
    wake_word: str = "computer"
    orchestrator_url: str = "http://localhost:8900/api/orchestrate"
    default_agent: str = "ScratchPad"
    tts_engine: str = "piper"
    say_voice: str = "Samantha"
    piper_model: str = str(Path.home() / "piper-voices" / "en_US-lessac-high.onnx")
    listen_timeout: float = 15.0
    max_record_duration: float = 10.0
    sample_rate: int = 16000
    stt_backend: str = "whisper"        # moonshine | whisper (moonshine faster but less accurate)
    whisper_model: str = "base"        # tiny|base|small|medium|large
    orchestrator_mode: bool = False
    project_cwd: str = str(Path(__file__).resolve().parent.parent.parent)

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        config = cls(
            porcupine_key=os.environ.get("PICOVOICE_API_KEY"),
            wake_word=os.environ.get("SUTRA_WAKE_WORD", "computer"),
            orchestrator_url=os.environ.get("SUTRA_URL", "http://localhost:8900/api/orchestrate"),
            default_agent=os.environ.get("SUTRA_AGENT", "ScratchPad"),
            tts_engine=os.environ.get("SUTRA_TTS", "piper"),
            say_voice=os.environ.get("SUTRA_SAY_VOICE", "Samantha"),
            whisper_model=os.environ.get("SUTRA_WHISPER_MODEL", "base"),
            stt_backend=os.environ.get("SUTRA_STT", "whisper"),
        )

        piper_model = os.environ.get("SUTRA_PIPER_MODEL")
        if piper_model:
            config.piper_model = piper_model

        cwd = os.environ.get("SUTRA_PROJECT_CWD")
        if cwd:
            config.project_cwd = cwd

        return config
