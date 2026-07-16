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
from services.audio_cleanup import AudioCleanupService
from services.audio_queue import AudioQueue
from services.audio_converter import AudioConverter
from services.audio_pipeline import AudioPipeline, AudioTranscriptionStage
from services.audio_upload import AudioUploadService
from services.llm_service import (
    LLMService,
    OpenAIResponsesLLMService,
    UnavailableLLMService,
)
from services.stt.transcription_service import Transcriber, TranscriptionService
from services.tts_service import (
    OpenAISpeechTTSService,
    TTSService,
    UnavailableTTSService,
)

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
    llm_service: LLMService | None = None,
    tts_service: TTSService | None = None,
    audio_cleanup_service: AudioCleanupService | None = None,
) -> FastAPI:
    """Cria a aplicacao com dependencias substituiveis nos testes."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await application.state.audio_cleanup_service.start()
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
        if (
            application.state.audio_pipeline is None
            and application.state.transcription_service is not None
        ):
            converter = AudioConverter(config)
            llm = llm_service
            tts = tts_service
            if llm is None:
                llm = (
                    OpenAIResponsesLLMService(config)
                    if config.ai_api_key
                    else UnavailableLLMService()
                )
            if tts is None:
                tts = (
                    OpenAISpeechTTSService(config)
                    if config.ai_api_key
                    else UnavailableTTSService()
                )
            stage = AudioTranscriptionStage(
                config,
                application.state.audio_upload_service.jobs,
                converter,
                application.state.transcription_service,
            )
            application.state.audio_pipeline = AudioPipeline(
                config,
                application.state.audio_upload_service.jobs,
                stage,
                llm,
                tts,
                converter,
                application.state.audio_queue,
            )
        try:
            yield
        finally:
            logger.info("event=service.shutdown_started component=backend")
            pipeline = application.state.audio_pipeline
            shutdown = getattr(pipeline, "shutdown", None)
            if shutdown is not None:
                await shutdown()
            await application.state.audio_cleanup_service.shutdown()
            logger.info("event=service.shutdown_completed component=backend")

    config = audio_input_config or (
        audio_upload_service.config
        if audio_upload_service is not None
        else AudioInputConfig.from_env()
    )
    application = FastAPI(title="ESP32 Audio Backend", lifespan=lifespan)
    application.state.audio_queue = audio_queue or AudioQueue()
    application.state.transcription_service = transcription_service
    application.state.audio_upload_service = audio_upload_service or AudioUploadService(
        config, AudioJobStore()
    )
    application.state.audio_cleanup_service = (
        audio_cleanup_service
        or AudioCleanupService(config, application.state.audio_upload_service.jobs)
    )
    application.state.audio_pipeline = audio_pipeline
    application.include_router(audio_router)
    application.include_router(audio_input_router)
    return application


app = create_app(load_stt=True)
