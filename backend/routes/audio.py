"""Endpoints HTTP para enfileirar e consumir audio PCM."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Request, Body
from fastapi.responses import JSONResponse, Response, StreamingResponse

from services.audio_queue import AudioQueue
from utils.pcm import strip_wav_header, validate_pcm

from services.stt.whisper_transcriber import WhisperTranscriber

router = APIRouter()
logger = logging.getLogger(__name__)


def _queue(request: Request) -> AudioQueue:
    return request.app.state.audio_queue


@router.post("/queue", status_code=202)
async def queue_audio(request: Request) -> Response:
    try:
        pcm = strip_wav_header(await request.body())
        validate_pcm(pcm)
        await _queue(request).enqueue(pcm)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    return JSONResponse(
        status_code=202,
        content={"status": "queued", "bytes": len(pcm)},
    )


@router.get("/audio/stream")
async def audio_stream(
    request: Request,
    audio_format: str | None = Header(default=None, alias="X-Audio-Format"),
    sample_rate: str | None = Header(default=None, alias="X-Audio-Sample-Rate"),
    channels: str | None = Header(default=None, alias="X-Audio-Channels"),
) -> Response:
    logger.info(
        "audio stream solicitado: format=%s sample_rate=%s channels=%s",
        audio_format,
        sample_rate,
        channels,
    )

    iterator = _queue(request).consume()
    try:
        first_chunk = await anext(iterator)
    except StopAsyncIteration:
        return Response(status_code=204)
    except RuntimeError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})

    async def with_first_chunk() -> AsyncIterator[bytes]:
        try:
            yield first_chunk
            async for chunk in iterator:
                yield chunk
        finally:
            await iterator.aclose()

    return StreamingResponse(
        with_first_chunk(),
        media_type="application/octet-stream",
    )


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    audio_queue = _queue(request)
    return {
        "status": "ok",
        "audio_ready": audio_queue.peek(),
        "stream_active": audio_queue.stream_active,
    }

transcriber = WhisperTranscriber()

@router.post("/transcribe")
async def transcribe_audio(audio_path: str = Body(..., embed=True)): 
    try:
        # Passa o caminho do áudio recebido para o transcritor
        text = transcriber.transcribe(audio_path)
        return {"status": "success", "text": text}
    
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"Erro ao transcrever": str(e)})