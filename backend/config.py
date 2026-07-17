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
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    tts_api_key: str = ""
    tts_base_url: str = "https://api.openai.com/v1"
    ai_timeout_seconds: float = 60.0
    llm_model: str = "deepseek-v4-flash"
    llm_max_output_tokens: int = 200
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"
    cleanup_interval_seconds: float = 300.0
    abandoned_file_age_seconds: float = 900.0
    job_retention_seconds: float = 3600.0
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
            or self.cleanup_interval_seconds <= 0
            or self.abandoned_file_age_seconds <= 0
            or self.job_retention_seconds <= 0
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
            llm_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            llm_base_url=os.getenv(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
            ),
            tts_api_key=os.getenv("OPENAI_API_KEY", ""),
            tts_base_url=os.getenv(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ),
            ai_timeout_seconds=float(os.getenv("AI_TIMEOUT_SECONDS", "60")),
            llm_model=os.getenv("LLM_MODEL", "deepseek-v4-flash"),
            llm_max_output_tokens=_positive_int("LLM_MAX_OUTPUT_TOKENS", 200),
            tts_model=os.getenv("TTS_MODEL", "gpt-4o-mini-tts"),
            tts_voice=os.getenv("TTS_VOICE", "alloy"),
            cleanup_interval_seconds=float(
                os.getenv("AUDIO_CLEANUP_INTERVAL_SECONDS", "300")
            ),
            abandoned_file_age_seconds=float(
                os.getenv("AUDIO_ABANDONED_FILE_AGE_SECONDS", "900")
            ),
            job_retention_seconds=float(
                os.getenv("AUDIO_JOB_RETENTION_SECONDS", "3600")
            ),
        )
