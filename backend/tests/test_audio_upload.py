import asyncio
import hashlib
from pathlib import Path

import pytest

from config import AudioInputConfig
from services.audio_upload import (
    AudioUploadBusy,
    AudioUploadIncomplete,
    AudioUploadService,
    AudioUploadTooLarge,
)


def make_service(root: Path, *, max_bytes: int = 1024) -> AudioUploadService:
    return AudioUploadService(
        AudioInputConfig(
            input_dir=root,
            max_bytes=max_bytes,
            chunk_size=4,
            device_token="test-token",
        )
    )


async def receive(
    service: AudioUploadService,
    chunks,
    *,
    expected_size: int,
    filename: str = "recording.webm",
):
    async def stream():
        for chunk in chunks:
            yield chunk

    return await service.receive(
        stream(),
        expected_size=expected_size,
        request_id="esp32-00001",
        device_id="esp32-test",
        original_filename=filename,
        content_type="audio/webm",
    )


def test_fragmented_upload_is_written_progressively(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = make_service(tmp_path)
        payload = b"abcdefghijklmno"

        async def stream():
            yield payload[:3]
            part = next(tmp_path.glob("*.part"))
            assert part.read_bytes() == payload[:3]
            yield payload[3:10]
            assert part.read_bytes() == payload[:10]
            yield payload[10:]

        result = await service.receive(
            stream(),
            expected_size=len(payload),
            request_id="esp32-00001",
            device_id="esp32-test",
            original_filename="recording.webm",
            content_type="audio/webm",
        )
        assert result.path.read_bytes() == payload
        assert result.sha256 == hashlib.sha256(payload).hexdigest()
        assert not list(tmp_path.glob("*.part"))

    asyncio.run(scenario())


def test_empty_and_incomplete_uploads_are_removed(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = make_service(tmp_path)
        with pytest.raises(AudioUploadIncomplete):
            await receive(service, [], expected_size=3)
        with pytest.raises(AudioUploadIncomplete):
            await receive(service, [b"ab"], expected_size=3)
        assert not list(tmp_path.iterdir())

    asyncio.run(scenario())


def test_stream_limit_is_enforced_and_partial_file_removed(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = make_service(tmp_path, max_bytes=5)
        with pytest.raises(AudioUploadTooLarge):
            await receive(service, [b"abcd", b"ef"], expected_size=5)
        assert not list(tmp_path.iterdir())

    asyncio.run(scenario())


def test_cancelled_upload_removes_part(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = make_service(tmp_path)

        async def cancelled_stream():
            yield b"ab"
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await service.receive(
                cancelled_stream(),
                expected_size=4,
                request_id="esp32-00001",
                device_id="esp32-test",
                original_filename="recording.webm",
                content_type="audio/webm",
            )
        assert not list(tmp_path.iterdir())

    asyncio.run(scenario())


def test_only_one_upload_is_active(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = make_service(tmp_path)
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def slow_stream():
            yield b"a"
            first_started.set()
            await release_first.wait()
            yield b"b"

        first = asyncio.create_task(
            service.receive(
                slow_stream(),
                expected_size=2,
                request_id="esp32-00001",
                device_id="esp32-test",
                original_filename="first.webm",
                content_type="audio/webm",
            )
        )
        await first_started.wait()
        with pytest.raises(AudioUploadBusy):
            await receive(service, [b"x"], expected_size=1)
        release_first.set()
        await first

    asyncio.run(scenario())


def test_client_filename_never_controls_path(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = make_service(tmp_path)
        result = await receive(
            service,
            [b"safe"],
            expected_size=4,
            filename="../../outside/evil.webm",
        )
        assert result.path.parent == tmp_path
        assert result.path.name.endswith(".upload")
        assert "evil" not in result.path.name

    asyncio.run(scenario())
