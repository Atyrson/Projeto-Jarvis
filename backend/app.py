"""Fabrica da aplicacao FastAPI."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import AudioInputConfig
from routes.audio import router as audio_router
from routes.audio_input import router as audio_input_router
from models.audio_input import AudioJobStore
from services.audio_queue import AudioQueue
from services.audio_upload import AudioUploadService
from services.stt.transcription_service import Transcriber, TranscriptionService

logger = logging.getLogger(__name__)


def _whisper_factory() -> Transcriber:
    from services.stt.whisper_transcriber import WhisperTranscriber

    model_dir = os.getenv("STT_MODEL_DIR")
    return WhisperTranscriber(
        os.getenv("STT_MODEL", "base"),
        download_root=model_dir or None,
        ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
    )


def create_app(
    *,
    audio_queue: AudioQueue | None = None,
    transcription_service: TranscriptionService | None = None,
    transcriber_factory: Callable[[], Transcriber] | None = None,
    load_stt: bool = False,
    audio_input_config: AudioInputConfig | None = None,
    audio_upload_service: AudioUploadService | None = None,
    audio_pipeline: object | None = None,
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
    config = audio_input_config or AudioInputConfig.from_env()
    application.state.audio_upload_service = audio_upload_service or AudioUploadService(
        config, AudioJobStore()
    )
    application.state.audio_pipeline = audio_pipeline
    application.include_router(audio_router)
    application.include_router(audio_input_router)
    return application


app = create_app(load_stt=True)
