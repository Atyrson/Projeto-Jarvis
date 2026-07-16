import asyncio
import struct

import httpx

from app import create_app
from services.audio_queue import AudioQueue


def request(method: str, path: str, *, queue=None, **kwargs) -> httpx.Response:
    async def scenario() -> httpx.Response:
        app = create_app(audio_queue=queue)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(scenario())


def test_queue_valid_pcm() -> None:
    response = request("POST", "/queue", content=b"\x00\x01\x02\x03")
    assert response.status_code == 202
    assert response.json() == {"status": "queued", "bytes": 4}


def test_queue_empty_body() -> None:
    response = request("POST", "/queue", content=b"")
    assert response.status_code == 400
    assert "error" in response.json()


def test_queue_odd_size_body() -> None:
    response = request("POST", "/queue", content=b"\x00\x01\x02")
    assert response.status_code == 400


def test_queue_strips_wav_header() -> None:
    async def scenario() -> None:
        queue = AudioQueue()
        pcm = b"\x01\x02\x03\x04"
        fmt = b"fmt " + struct.pack("<I", 4) + b"meta"
        data = b"data" + struct.pack("<I", len(pcm)) + pcm
        body = b"WAVE" + fmt + data
        wav = b"RIFF" + struct.pack("<I", len(body)) + body
        app = create_app(audio_queue=queue)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            queued = await client.post("/queue", content=wav)
            streamed = await client.get("/audio/stream")
        assert queued.json()["bytes"] == len(pcm)
        assert streamed.content == pcm

    asyncio.run(scenario())

def test_stream_returns_pcm() -> None:
    async def scenario() -> None:
        pcm = b"\x00\x01" * 2000
        queue = AudioQueue()
        await queue.enqueue(pcm)
        app = create_app(audio_queue=queue)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/audio/stream",
                headers={
                    "Accept": "application/octet-stream",
                    "X-Audio-Format": "pcm_s16le",
                    "X-Audio-Sample-Rate": "16000",
                    "X-Audio-Channels": "1",
                },
            )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.content == pcm

    asyncio.run(scenario())


def test_stream_no_content_when_empty() -> None:
    response = request(
        "GET", "/audio/stream", queue=AudioQueue(wait_timeout=0.01)
    )
    assert response.status_code == 204
    assert response.content == b""


def test_health_endpoint() -> None:
    response = request("GET", "/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "audio_ready": False,
        "stream_active": False,
    }


def test_stream_conflict() -> None:
    async def scenario() -> None:
        queue = AudioQueue(wait_timeout=1)
        active = queue.consume()
        waiting = asyncio.create_task(anext(active))
        await asyncio.sleep(0)

        app = create_app(audio_queue=queue)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/audio/stream")

        assert response.status_code == 409
        assert response.json() == {"error": "ja existe um stream ativo"}
        waiting.cancel()
        try:
            await waiting
        except asyncio.CancelledError:
            pass
        await active.aclose()

    asyncio.run(scenario())
