"""Montagem progressiva e segura de uploads de audio."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from config import AudioInputConfig
from models.audio_input import AudioJob, AudioJobStatus, AudioJobStore

logger = logging.getLogger(__name__)


class AudioUploadError(Exception):
    status_code = 400
    error_code = "upload_invalid"


class AudioUploadBusy(AudioUploadError):
    status_code = 409
    error_code = "upload_busy"


class AudioUploadTooLarge(AudioUploadError):
    status_code = 413
    error_code = "upload_too_large"


class AudioUploadIncomplete(AudioUploadError):
    error_code = "upload_incomplete"


@dataclass(frozen=True, slots=True)
class AudioUploadResult:
    job_id: str
    path: Path
    bytes_received: int
    sha256: str


class AudioUploadService:
    def __init__(
        self, config: AudioInputConfig, job_store: AudioJobStore | None = None
    ) -> None:
        self.config = config
        self.jobs = job_store or AudioJobStore()
        self._active = 0
        self._active_lock = asyncio.Lock()

    async def _reserve(self) -> None:
        async with self._active_lock:
            if self._active >= self.config.max_concurrent:
                raise AudioUploadBusy("ja existe upload ativo")
            self._active += 1

    async def _release(self) -> None:
        async with self._active_lock:
            self._active -= 1

    async def receive(
        self,
        stream: AsyncIterator[bytes],
        *,
        expected_size: int,
        request_id: str,
        device_id: str,
        original_filename: str,
        content_type: str,
    ) -> AudioUploadResult:
        if expected_size <= 0:
            raise AudioUploadIncomplete("corpo vazio ou tamanho invalido")
        if expected_size > self.config.max_bytes:
            raise AudioUploadTooLarge("arquivo acima do limite")

        await self._reserve()
        job_id = uuid.uuid4().hex
        part_path = self.config.input_dir / f"{job_id}.part"
        complete_path = self.config.input_dir / f"{job_id}.upload"
        received = 0
        digest = hashlib.sha256()
        started = time.monotonic()
        now = datetime.now(UTC)
        job = AudioJob(
            job_id=job_id,
            status=AudioJobStatus.RECEIVING,
            request_id=request_id,
            device_id=device_id,
            original_filename=original_filename,
            content_type=content_type,
            bytes_expected=expected_size,
            created_at=now,
            updated_at=now,
        )
        await self.jobs.create(job)
        self.config.input_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "event=upload.request_received phase=receiving request_id=%s "
            "job_id=%s device_id=%s bytes_expected=%d",
            request_id,
            job_id,
            device_id,
            expected_size,
        )

        try:
            with part_path.open("xb") as destination:
                async for chunk in stream:
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > self.config.max_bytes:
                        raise AudioUploadTooLarge("arquivo acima do limite")
                    if received > expected_size:
                        raise AudioUploadIncomplete("corpo excede o tamanho declarado")
                    destination.write(chunk)
                    destination.flush()
                    digest.update(chunk)
                    if received == expected_size or received % (256 * 1024) < len(chunk):
                        logger.info(
                            "event=upload.progress phase=receiving request_id=%s "
                            "job_id=%s bytes_received=%d",
                            request_id,
                            job_id,
                            received,
                        )
                destination.flush()
                os.fsync(destination.fileno())

            if received == 0:
                raise AudioUploadIncomplete("corpo vazio")
            if received != expected_size:
                raise AudioUploadIncomplete(
                    f"tamanho recebido diverge do declarado: {received}/{expected_size}"
                )

            os.replace(part_path, complete_path)
            sha256 = digest.hexdigest()
            await self.jobs.update(
                job_id,
                status=AudioJobStatus.ACCEPTED,
                bytes_received=received,
                sha256=sha256,
                file_path=complete_path,
            )
            logger.info(
                "event=upload.completed phase=receiving request_id=%s job_id=%s "
                "device_id=%s bytes_expected=%d bytes_received=%d elapsed_ms=%d "
                "result=success sha256=%s",
                request_id,
                job_id,
                device_id,
                expected_size,
                received,
                round((time.monotonic() - started) * 1000),
                sha256,
            )
            return AudioUploadResult(job_id, complete_path, received, sha256)
        except asyncio.CancelledError:
            await self._remove(part_path)
            await self.jobs.update(
                job_id,
                status=AudioJobStatus.FAILED,
                bytes_received=received,
                error="upload_cancelled",
            )
            logger.warning(
                "event=upload.cancelled request_id=%s job_id=%s "
                "bytes_received=%d result=cancelled",
                request_id,
                job_id,
                received,
            )
            raise
        except Exception as exc:
            await self._remove(part_path)
            await self._remove(complete_path)
            error_code = (
                exc.error_code if isinstance(exc, AudioUploadError) else "upload_failed"
            )
            await self.jobs.update(
                job_id,
                status=AudioJobStatus.FAILED,
                bytes_received=received,
                error=error_code,
            )
            logger.warning(
                "event=upload.rejected request_id=%s job_id=%s "
                "bytes_received=%d result=rejected error_code=%s",
                request_id,
                job_id,
                received,
                error_code,
            )
            raise
        finally:
            await self._release()

    @staticmethod
    async def _remove(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("event=upload.cleanup_failed")
