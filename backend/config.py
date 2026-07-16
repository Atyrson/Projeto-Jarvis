"""Configuracao do caminho de entrada de audio."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} deve ser maior que zero")
    return value


@dataclass(frozen=True, slots=True)
class AudioInputConfig:
    max_bytes: int = 10 * 1024 * 1024
    max_duration_seconds: float = 120.0
    chunk_size: int = 64 * 1024
    input_dir: Path = field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "esp32-audio-input"
    )
    max_concurrent: int = 1
    device_token: str = ""
    stt_timeout_seconds: float = 180.0
    media_timeout_seconds: float = 30.0
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    ai_api_key: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_timeout_seconds: float = 60.0
    llm_model: str = "gpt-5.6-luna"
    llm_max_output_tokens: int = 200
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"
    allowed_mime_types: frozenset[str] = frozenset(
        {
            "audio/aac",
            "audio/flac",
            "audio/m4a",
            "audio/mp4",
            "audio/mpeg",
            "audio/ogg",
            "audio/wav",
            "audio/webm",
            "audio/x-m4a",
            "audio/x-wav",
        }
    )

    def __post_init__(self) -> None:
        if self.max_bytes <= 0 or self.chunk_size <= 0 or self.max_concurrent <= 0:
            raise ValueError("limites de audio devem ser maiores que zero")
        if (
            self.max_duration_seconds <= 0
            or self.stt_timeout_seconds <= 0
            or self.media_timeout_seconds <= 0
            or self.ai_timeout_seconds <= 0
        ):
            raise ValueError("timeouts e duracao devem ser maiores que zero")
        if self.llm_max_output_tokens <= 0:
            raise ValueError("LLM_MAX_OUTPUT_TOKENS deve ser maior que zero")

    @classmethod
    def from_env(cls) -> "AudioInputConfig":
        return cls(
            max_bytes=_positive_int("AUDIO_INPUT_MAX_BYTES", 10 * 1024 * 1024),
            max_duration_seconds=float(
                os.getenv("AUDIO_INPUT_MAX_DURATION_SECONDS", "120")
            ),
            chunk_size=_positive_int("AUDIO_INPUT_CHUNK_SIZE", 64 * 1024),
            input_dir=Path(
                os.getenv(
                    "AUDIO_INPUT_DIR",
                    str(Path(tempfile.gettempdir()) / "esp32-audio-input"),
                )
            ),
            max_concurrent=_positive_int("AUDIO_INPUT_MAX_CONCURRENT", 1),
            device_token=os.getenv("AUDIO_INPUT_DEVICE_TOKEN", ""),
            stt_timeout_seconds=float(os.getenv("STT_TIMEOUT_SECONDS", "180")),
            media_timeout_seconds=float(
                os.getenv("AUDIO_MEDIA_TIMEOUT_SECONDS", "30")
            ),
            ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
            ffprobe_bin=os.getenv("FFPROBE_BIN", "ffprobe"),
            ai_api_key=os.getenv("OPENAI_API_KEY", ""),
            ai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            ai_timeout_seconds=float(os.getenv("AI_TIMEOUT_SECONDS", "60")),
            llm_model=os.getenv("LLM_MODEL", "gpt-5.6-luna"),
            llm_max_output_tokens=_positive_int("LLM_MAX_OUTPUT_TOKENS", 200),
            tts_model=os.getenv("TTS_MODEL", "tts-1"),
            tts_voice=os.getenv("TTS_VOICE", "alloy"),
        )
