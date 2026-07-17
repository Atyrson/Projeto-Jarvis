import asyncio
import hashlib
from pathlib import Path

from config import AudioInputConfig
from services.audio_upload import AudioUploadService


def test_repeated_streamed_uploads_leave_no_temporary_files(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = AudioUploadService(
            AudioInputConfig(
                input_dir=tmp_path,
                device_token="load-test",
                max_bytes=128 * 1024,
            )
        )
        chunk = bytes(range(256)) * 16
        chunks_per_upload = 16
        expected_size = len(chunk) * chunks_per_upload
        expected_hash = hashlib.sha256(chunk * chunks_per_upload).hexdigest()

        for index in range(25):
            async def stream():
                for _ in range(chunks_per_upload):
                    yield chunk

            result = await service.receive(
                stream(),
                expected_size=expected_size,
                request_id=f"load-{index:03d}",
                device_id="esp32-load",
                original_filename="load.webm",
                content_type="audio/webm",
            )
            assert result.sha256 == expected_hash
            assert result.bytes_received == expected_size
            result.path.unlink()

        assert not list(tmp_path.iterdir())

    asyncio.run(scenario())
