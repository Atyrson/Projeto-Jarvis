"""Adaptador do modelo Whisper mantido pelo modulo STT existente."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import whisper

from .transcription_service import AudioPath, Transcriber

logger = logging.getLogger(__name__)


class WhisperTranscriber(Transcriber):
    def __init__(
        self,
        model_name: str = "base",
        *,
        download_root: str | Path | None = None,
        ffmpeg_bin: str | Path = "ffmpeg",
    ) -> None:
        ffmpeg_path = Path(ffmpeg_bin)
        if ffmpeg_path.parent != Path("."):
            directory = str(ffmpeg_path.resolve().parent)
            path_entries = os.environ.get("PATH", "").split(os.pathsep)
            if directory not in path_entries:
                os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
        started = time.monotonic()
        logger.info("event=stt.model_loading model=%s", model_name)
        options = {} if download_root is None else {"download_root": str(download_root)}
        self._model = whisper.load_model(model_name, **options)
        logger.info(
            "event=stt.model_ready model=%s elapsed_ms=%d",
            model_name,
            round((time.monotonic() - started) * 1000),
        )

    def transcribe(self, audio_path: AudioPath) -> str:
        started = time.monotonic()
        logger.info("event=stt.started")
        try:
            result = self._model.transcribe(str(audio_path))
            text = result["text"].strip()
        except Exception:
            logger.exception(
                "event=stt.failed elapsed_ms=%d",
                round((time.monotonic() - started) * 1000),
            )
            raise
        logger.info(
            "event=stt.completed elapsed_ms=%d characters=%d",
            round((time.monotonic() - started) * 1000),
            len(text),
        )
        return text
