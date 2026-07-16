"""Adaptador do modelo Whisper mantido pelo modulo STT existente."""

from __future__ import annotations

import logging
import time

import whisper

from .transcription_service import AudioPath, Transcriber

logger = logging.getLogger(__name__)


class WhisperTranscriber(Transcriber):
    def __init__(self, model_name: str = "base") -> None:
        started = time.monotonic()
        logger.info("event=stt.model_loading model=%s", model_name)
        self._model = whisper.load_model(model_name)
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
