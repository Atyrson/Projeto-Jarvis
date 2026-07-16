import asyncio
from pathlib import Path

import httpx

from app import create_app
from config import AudioInputConfig
from services.audio_upload import AudioUploadService


class FakePipeline:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)


def config(root: Path, *, max_bytes: int = 1024) -> AudioInputConfig:
    return AudioInputConfig(
        input_dir=root,
        max_bytes=max_bytes,
        device_token="device-secret",
    )


def headers(**overrides: str) -> dict[str, str]:
    values = {
        "Content-Type": "audio/webm",
        "X-Audio-Filename": "recording.webm",
        "X-Request-Id": "esp32-00042",
        "X-Source-Device": "esp32",
        "X-Device-Id": "esp32-test",
        "X-Device-Token": "device-secret",
    }
    values.update(overrides)
    return values


def test_upload_returns_202_and_status_can_be_queried(tmp_path: Path) -> None:
    async def scenario() -> None:
        pipeline = FakePipeline()
        application = create_app(
            audio_input_config=config(tmp_path), audio_pipeline=pipeline
        )
        transport = httpx.ASGITransport(app=application)
        payload = b"webm-fragmented-payload"

        async def fragmented():
            yield payload[:2]
            yield payload[2:11]
            yield payload[11:]

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/audio/input",
                headers=headers(**{"Content-Length": str(len(payload))}),
                content=fragmented(),
            )
            assert response.status_code == 202
            accepted = response.json()
            status = await client.get(f"/audio/input/{accepted['job_id']}")

        assert accepted["bytes"] == len(payload)
        assert len(accepted["sha256"]) == 64
        assert pipeline.submitted == [accepted["job_id"]]
        assert status.status_code == 200
        assert status.json()["status"] == "accepted"
        assert status.json()["error"] is None

    asyncio.run(scenario())


def test_bad_token_is_401_and_audio_is_not_written(tmp_path: Path) -> None:
    async def scenario() -> None:
        application = create_app(audio_input_config=config(tmp_path))
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/audio/input",
                headers=headers(**{"X-Device-Token": "wrong"}),
                content=b"audio",
            )
        assert response.status_code == 401
        assert not list(tmp_path.iterdir())

    asyncio.run(scenario())


def test_rejected_mime_is_415(tmp_path: Path) -> None:
    async def scenario() -> None:
        application = create_app(audio_input_config=config(tmp_path))
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/audio/input",
                headers=headers(**{"Content-Type": "application/json"}),
                content=b"{}",
            )
        assert response.status_code == 415

    asyncio.run(scenario())


def test_declared_limit_is_413(tmp_path: Path) -> None:
    async def scenario() -> None:
        application = create_app(audio_input_config=config(tmp_path, max_bytes=4))
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/audio/input", headers=headers(), content=b"12345"
            )
        assert response.status_code == 413

    asyncio.run(scenario())


def test_existing_routes_remain_compatible(tmp_path: Path) -> None:
    async def scenario() -> None:
        application = create_app(audio_input_config=config(tmp_path))
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            queued = await client.post("/queue", content=b"\x00\x01")
        assert health.status_code == 200
        assert queued.status_code == 202

    asyncio.run(scenario())


def test_second_upload_returns_409(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = AudioUploadService(config(tmp_path))
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
                request_id="esp32-first",
                device_id="esp32-test",
                original_filename="first.webm",
                content_type="audio/webm",
            )
        )
        await first_started.wait()
        application = create_app(audio_upload_service=service)
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/audio/input", headers=headers(), content=b"x"
            )
        assert response.status_code == 409
        release_first.set()
        await first

    asyncio.run(scenario())
