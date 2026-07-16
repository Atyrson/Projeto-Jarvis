"""Teste ponta a ponta do contrato de rede usado por http_audio_player.c."""

import asyncio
import http.client
import re
import socket
from pathlib import Path

import uvicorn

from app import create_app
from services.audio_queue import AudioQueue


FIRMWARE_SOURCE = Path(__file__).parents[2] / "main" / "http_audio_player.c"


def test_firmware_timeout_covers_backend_long_poll() -> None:
    source = FIRMWARE_SOURCE.read_text(encoding="utf-8")
    match = re.search(r"#define HTTP_TIMEOUT_MS (\d+)", source)
    assert match is not None
    assert int(match.group(1)) > 30_000
    assert ".timeout_ms = HTTP_TIMEOUT_MS" in source


def test_uvicorn_stream_matches_esp32_http_contract() -> None:
    async def scenario() -> None:
        pcm = bytes(range(256)) * 25
        queue = AudioQueue(wait_timeout=0.1)
        await queue.enqueue(pcm)

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        config = uvicorn.Config(
            create_app(audio_queue=queue),
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
        server = uvicorn.Server(config)
        serve_task = asyncio.create_task(server.serve(sockets=[listener]))

        try:
            while not server.started:
                await asyncio.sleep(0.01)

            def firmware_request() -> tuple[int, str | None, str | None, bytes]:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=35)
                connection.request(
                    "GET",
                    "/audio/stream",
                    headers={
                        "User-Agent": "esp32-http-audio/1.0",
                        "Accept": "application/octet-stream",
                        "X-Audio-Format": "pcm_s16le",
                        "X-Audio-Sample-Rate": "16000",
                        "X-Audio-Channels": "1",
                    },
                )
                response = connection.getresponse()
                received = bytearray()
                while block := response.read(2048):
                    received.extend(block)
                result = (
                    response.status,
                    response.getheader("Content-Type"),
                    response.getheader("Transfer-Encoding"),
                    bytes(received),
                )
                connection.close()
                return result

            status, content_type, transfer_encoding, received = await asyncio.to_thread(
                firmware_request
            )
            assert status == 200
            assert content_type == "application/octet-stream"
            assert transfer_encoding == "chunked"
            assert received == pcm
            assert len(received) % 2 == 0
        finally:
            server.should_exit = True
            await serve_task
            listener.close()

    asyncio.run(scenario())
