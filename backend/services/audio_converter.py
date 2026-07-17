"""Inspecao e conversao segura de audio por FFmpeg/ffprobe."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from config import AudioInputConfig

logger = logging.getLogger(__name__)


class AudioConversionError(Exception):
    error_code = "media_invalid"


class AudioDurationExceeded(AudioConversionError):
    error_code = "media_too_long"


class AudioConversionTimeout(AudioConversionError):
    error_code = "media_timeout"


@dataclass(frozen=True, slots=True)
class MediaProbe:
    format_name: str
    codec_name: str
    duration_seconds: float


class AudioConverter:
    _allowed_formats = frozenset(
        {"aac", "flac", "m4a", "matroska", "mov", "mp3", "mp4", "ogg", "wav", "webm"}
    )

    def __init__(self, config: AudioInputConfig) -> None:
        self.config = config

    async def _run(self, *command: str, event: str) -> tuple[bytes, bytes]:
        started = time.monotonic()
        logger.info("event=%s_started", event)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            logger.error("event=media.tool_unavailable error_code=media_tool_unavailable")
            raise AudioConversionError("ferramenta de midia indisponivel") from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.config.media_timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            logger.error(
                "event=%s_failed elapsed_ms=%d error_code=media_timeout",
                event,
                round((time.monotonic() - started) * 1000),
            )
            raise AudioConversionTimeout("timeout na ferramenta de midia") from exc
        if process.returncode != 0:
            logger.warning(
                "event=%s_failed elapsed_ms=%d error_code=media_invalid stderr_bytes=%d",
                event,
                round((time.monotonic() - started) * 1000),
                len(stderr),
            )
            raise AudioConversionError("arquivo de audio invalido")
        logger.info(
            "event=%s_completed elapsed_ms=%d",
            event,
            round((time.monotonic() - started) * 1000),
        )
        return stdout, stderr

    async def probe(self, source: Path) -> MediaProbe:
        stdout, _ = await self._run(
            self.config.ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration:stream=codec_type,codec_name",
            "-of",
            "json",
            str(source),
            event="media.probe",
        )
        try:
            document = json.loads(stdout)
            format_data = document["format"]
            format_name = str(format_data["format_name"])
            duration = float(format_data["duration"])
            audio_stream = next(
                stream
                for stream in document.get("streams", [])
                if stream.get("codec_type") == "audio"
            )
            codec_name = str(audio_stream["codec_name"])
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AudioConversionError("arquivo sem stream de audio valido") from exc
        detected_formats = set(format_name.split(","))
        if not detected_formats.intersection(self._allowed_formats):
            raise AudioConversionError("container de audio nao suportado")
        if duration <= 0:
            raise AudioConversionError("duracao de audio invalida")
        if duration > self.config.max_duration_seconds:
            raise AudioDurationExceeded("duracao acima do limite")
        logger.info(
            "event=media.probe_completed duration_ms=%d format=%s codec=%s",
            round(duration * 1000),
            format_name,
            codec_name,
        )
        return MediaProbe(format_name, codec_name, duration)

    async def normalize_input(self, source: Path, destination: Path) -> MediaProbe:
        probe = await self.probe(source)
        destination.unlink(missing_ok=True)
        try:
            await self._run(
                self.config.ffmpeg_bin,
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(destination),
                event="media.conversion",
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if not destination.is_file() or destination.stat().st_size <= 44:
            destination.unlink(missing_ok=True)
            raise AudioConversionError("conversao nao produziu audio")
        return probe

    async def convert_to_pcm(self, source: Path, destination: Path) -> bytes:
        destination.unlink(missing_ok=True)
        try:
            await self._run(
                self.config.ffmpeg_bin,
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(destination),
                event="output.conversion",
            )
            return await asyncio.to_thread(destination.read_bytes)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
