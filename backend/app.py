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
    DeepSeekChatLLMService,
    LLMService,
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
    load_stt: bool | None = None,
    audio_input_config: AudioInputConfig | None = None,
    audio_upload_service: AudioUploadService | None = None,
    audio_pipeline: object | None = None,
    llm_service: LLMService | None = None,
    tts_service: TTSService | None = None,
    audio_cleanup_service: AudioCleanupService | None = None,
) -> FastAPI:
    """Cria a aplicacao com dependencias substituiveis nos testes."""
    print("[app] create_app: iniciando")
    if load_stt is None:
        load_stt = os.getenv("LOAD_STT", "false").lower() == "true"

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        print("[app] lifespan: inicio")
        print(f"[app] lifespan: load_stt={load_stt}")
        print(f"[app] lifespan: transcription_service_inicial={application.state.transcription_service is not None}")
        print(f"[app] lifespan: audio_pipeline_inicial={application.state.audio_pipeline is not None}")
        await application.state.audio_cleanup_service.start()
        print("[app] lifespan: audio_cleanup_service.start concluido")
        if application.state.transcription_service is None and load_stt:
            factory = transcriber_factory or _whisper_factory
            try:
                print("[app] lifespan: carregando transcriber")
                transcriber = await asyncio.to_thread(factory)
                print(f"[app] lifespan: transcriber carregado tipo={type(transcriber).__name__}")
                application.state.transcription_service = TranscriptionService(
                    transcriber,
                    max_concurrent=int(os.getenv("STT_MAX_CONCURRENT", "1")),
                )
                print("[app] lifespan: transcription_service inicializada")
            except Exception:
                print("[app] lifespan: erro ao carregar STT")
                import traceback

                traceback.print_exc()
        if (
            application.state.audio_pipeline is None
            and application.state.transcription_service is not None
        ):
            print("[app] lifespan: montando audio pipeline")
            converter = AudioConverter(config)
            llm = llm_service
            tts = tts_service
            if llm is None:
                print("[app] lifespan: criando LLM padrao")
                llm = (
                    DeepSeekChatLLMService(config)
                    if config.llm_api_key
                    else UnavailableLLMService()
                )
            print(f"[app] lifespan: llm={type(llm).__name__}")
            if tts is None:
                print("[app] lifespan: criando TTS padrao")
                tts = (
                    OpenAISpeechTTSService(config)
                    if config.tts_api_key
                    else UnavailableTTSService()
                )
            print(f"[app] lifespan: tts={type(tts).__name__}")
            stage = AudioTranscriptionStage(
                config,
                application.state.audio_upload_service.jobs,
                converter,
                application.state.transcription_service,
            )
            print("[app] lifespan: stage de transcricao criada")
            application.state.audio_pipeline = AudioPipeline(
                config,
                application.state.audio_upload_service.jobs,
                stage,
                llm,
                tts,
                converter,
                application.state.audio_queue,
            )
            print("[app] lifespan: audio pipeline inicializado")
        try:
            print("[app] lifespan: aplicacao pronta para servir")
            yield
        finally:
            print("[app] lifespan: shutdown iniciado")
            pipeline = application.state.audio_pipeline
            shutdown = getattr(pipeline, "shutdown", None)
            if shutdown is not None:
                print("[app] lifespan: chamando shutdown do pipeline")
                await shutdown()
                print("[app] lifespan: shutdown do pipeline concluido")
            await application.state.audio_cleanup_service.shutdown()
            print("[app] lifespan: shutdown da limpeza concluido")

    config = audio_input_config or (
        audio_upload_service.config
        if audio_upload_service is not None
        else AudioInputConfig.from_env()
    )
    print(f"[app] config carregada: {config}")
    application = FastAPI(title="ESP32 Audio Backend", lifespan=lifespan)
    application.state.audio_queue = audio_queue or AudioQueue()
    print(f"[app] audio_queue inicializada tipo={type(application.state.audio_queue).__name__}")
    application.state.transcription_service = transcription_service
    print(f"[app] transcription_service inicial={transcription_service is not None}")
    application.state.audio_upload_service = audio_upload_service or AudioUploadService(
        config, AudioJobStore()
    )
    print(f"[app] audio_upload_service inicializado tipo={type(application.state.audio_upload_service).__name__}")
    application.state.audio_cleanup_service = (
        audio_cleanup_service
        or AudioCleanupService(config, application.state.audio_upload_service.jobs)
    )
    print(f"[app] audio_cleanup_service inicializado tipo={type(application.state.audio_cleanup_service).__name__}")
    application.state.audio_pipeline = audio_pipeline
    print(f"[app] audio_pipeline inicial={audio_pipeline is not None}")
    application.include_router(audio_router)
    application.include_router(audio_input_router)
    print("[app] routers incluidos")
    return application

print("[app] importando app.py")
app = create_app(load_stt=True)
print("[app] app criado")