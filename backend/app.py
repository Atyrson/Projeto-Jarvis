"""Fabrica da aplicacao FastAPI."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from routes.audio import router as audio_router
from services.audio_queue import AudioQueue
from services.stt.transcription_service import Transcriber, TranscriptionService

logger = logging.getLogger(__name__)


def _whisper_factory() -> Transcriber:
    from services.stt.whisper_transcriber import WhisperTranscriber

    return WhisperTranscriber(os.getenv("STT_MODEL", "base"))


def create_app(
    *,
    audio_queue: AudioQueue | None = None,
    transcription_service: TranscriptionService | None = None,
    transcriber_factory: Callable[[], Transcriber] | None = None,
    load_stt: bool = False,
) -> FastAPI:
    """Cria a aplicacao com dependencias substituiveis nos testes."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if application.state.transcription_service is None and load_stt:
            factory = transcriber_factory or _whisper_factory
            try:
                transcriber = await asyncio.to_thread(factory)
                application.state.transcription_service = TranscriptionService(
                    transcriber,
                    max_concurrent=int(os.getenv("STT_MAX_CONCURRENT", "1")),
                )
            except Exception:
                logger.exception("event=stt.model_load_failed")
        yield

    application = FastAPI(title="ESP32 Audio Backend", lifespan=lifespan)
    application.state.audio_queue = audio_queue or AudioQueue()
    application.state.transcription_service = transcription_service
    application.include_router(audio_router)
    return application


app = create_app(load_stt=True)
