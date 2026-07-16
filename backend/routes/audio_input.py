"""Contrato HTTP do audio capturado pelo celular e encaminhado pela ESP32."""

from __future__ import annotations

import hmac
import logging
from typing import Protocol

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response

from services.audio_upload import AudioUploadError, AudioUploadService

router = APIRouter(prefix="/audio/input", tags=["audio-input"])
logger = logging.getLogger(__name__)


class PipelineSubmitter(Protocol):
    def submit(self, job_id: str) -> None: ...


def _upload_service(request: Request) -> AudioUploadService:
    return request.app.state.audio_upload_service


def _reject(status_code: int, error: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error})


@router.post("", status_code=202)
async def upload_audio(
    request: Request,
    content_length: str | None = Header(default=None, alias="Content-Length"),
    content_type: str | None = Header(default=None, alias="Content-Type"),
    filename: str = Header(default="audio", alias="X-Audio-Filename"),
    request_id: str = Header(default="", alias="X-Request-Id"),
    source: str = Header(default="", alias="X-Source-Device"),
    device_id: str = Header(default="", alias="X-Device-Id"),
    device_token: str = Header(default="", alias="X-Device-Token"),
) -> Response:
    service = _upload_service(request)
    expected_token = service.config.device_token
    if not expected_token:
        return _reject(503, "token do dispositivo nao configurado")
    if not hmac.compare_digest(device_token, expected_token):
        return _reject(401, "dispositivo nao autorizado")
    if source != "esp32" or not request_id or not device_id:
        return _reject(400, "headers de origem invalidos")
    if any(len(value) > 255 for value in (filename, request_id, device_id)):
        return _reject(400, "header acima do limite")
    if content_length is None:
        return _reject(411, "Content-Length obrigatorio")
    try:
        expected_size = int(content_length)
    except ValueError:
        return _reject(400, "Content-Length invalido")
    if expected_size <= 0:
        return _reject(400, "corpo vazio ou tamanho invalido")
    if expected_size > service.config.max_bytes:
        return _reject(413, "arquivo acima do limite")

    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type not in service.config.allowed_mime_types:
        return _reject(415, "tipo de audio nao suportado")

    try:
        result = await service.receive(
            request.stream(),
            expected_size=expected_size,
            request_id=request_id,
            device_id=device_id,
            original_filename=filename,
            content_type=media_type,
        )
    except AudioUploadError as exc:
        return _reject(exc.status_code, str(exc))
    except Exception:
        logger.exception("event=upload.failed request_id=%s", request_id)
        return _reject(500, "falha interna no upload")

    pipeline: PipelineSubmitter | None = getattr(request.app.state, "audio_pipeline", None)
    if pipeline is not None:
        pipeline.submit(result.job_id)
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "job_id": result.job_id,
            "bytes": result.bytes_received,
            "sha256": result.sha256,
        },
    )


@router.get("/{job_id}")
async def audio_job_status(request: Request, job_id: str) -> Response:
    if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
        return _reject(404, "job nao encontrado")
    job = await _upload_service(request).jobs.get(job_id)
    if job is None:
        return _reject(404, "job nao encontrado")
    return JSONResponse(content=job.public_dict())
