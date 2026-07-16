import asyncio
import time
from pathlib import Path

import httpx

from app import create_app
from services.stt.transcription_service import Transcriber, TranscriptionService


class FakeTranscriber(Transcriber):
    def __init__(self, text: str = "texto previsivel") -> None:
        self.text = text
        self.paths: list[Path] = []

    def transcribe(self, audio_path: str | Path) -> str:
        self.paths.append(Path(audio_path))
        return self.text


def test_transcription_service_runs_outside_event_loop() -> None:
    class SlowTranscriber(FakeTranscriber):
        def transcribe(self, audio_path: str | Path) -> str:
            time.sleep(0.05)
            return super().transcribe(audio_path)

    async def scenario() -> None:
        service = TranscriptionService(SlowTranscriber())
        operation = asyncio.create_task(service.transcribe_async("controlled.wav"))
        await asyncio.sleep(0.01)
        assert not operation.done()
        assert await operation == "texto previsivel"

    asyncio.run(scenario())


def test_diagnostic_route_uses_injected_service() -> None:
    async def scenario() -> None:
        fake = FakeTranscriber()
        application = create_app(transcription_service=TranscriptionService(fake))
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/transcribe", json={"audio_path": "controlled.wav"}
            )
        assert response.status_code == 200
        assert response.json() == {"status": "success", "text": fake.text}
        assert fake.paths == [Path("controlled.wav")]

    asyncio.run(scenario())


def test_diagnostic_route_does_not_load_model_implicitly() -> None:
    async def scenario() -> None:
        application = create_app()
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/transcribe", json={"audio_path": "arbitrary.wav"}
            )
        assert response.status_code == 503

    asyncio.run(scenario())
