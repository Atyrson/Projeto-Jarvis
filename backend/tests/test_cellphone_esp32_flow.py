"""Contrato TCP real do upload encaminhado pela ESP32."""

import asyncio
import hashlib
import http.client
import json
import socket
from pathlib import Path

import uvicorn

from app import create_app
from config import AudioInputConfig


class FakePipeline:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)


async def running_server(root: Path):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    pipeline = FakePipeline()
    application = create_app(
        audio_input_config=AudioInputConfig(
            input_dir=root, device_token="tcp-secret", max_bytes=1024 * 1024
        ),
        audio_pipeline=pipeline,
    )
    server = uvicorn.Server(
        uvicorn.Config(application, log_level="error", lifespan="on")
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    while not server.started:
        await asyncio.sleep(0.01)
    return listener, pipeline, application, server, task


def upload_headers(length: int) -> dict[str, str]:
    return {
        "Content-Type": "audio/webm",
        "Content-Length": str(length),
        "X-Audio-Filename": "phone.webm",
        "X-Request-Id": "esp32-tcp-0001",
        "X-Source-Device": "esp32",
        "X-Device-Id": "esp32-tcp",
        "X-Device-Token": "tcp-secret",
    }


def test_real_tcp_fragmentation_preserves_hash(tmp_path: Path) -> None:
    async def scenario() -> None:
        listener, pipeline, application, server, task = await running_server(tmp_path)
        port = listener.getsockname()[1]
        payload = bytes(range(251)) * 100

        def send_fragmented() -> tuple[int, dict[str, object]]:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.putrequest("POST", "/audio/input")
            for name, value in upload_headers(len(payload)).items():
                connection.putheader(name, value)
            connection.endheaders()
            for start in range(0, len(payload), 137):
                connection.send(payload[start : start + 137])
            response = connection.getresponse()
            document = json.loads(response.read())
            status = response.status
            connection.close()
            return status, document

        try:
            status, document = await asyncio.to_thread(send_fragmented)
            assert status == 202
            assert document["bytes"] == len(payload)
            expected_hash = hashlib.sha256(payload).hexdigest()
            assert document["sha256"] == expected_hash
            job = await application.state.audio_upload_service.jobs.get(
                str(document["job_id"])
            )
            assert job is not None and job.file_path is not None
            assert hashlib.sha256(job.file_path.read_bytes()).hexdigest() == expected_hash
            assert pipeline.submitted == [document["job_id"]]
        finally:
            server.should_exit = True
            await task
            listener.close()

    asyncio.run(scenario())


def test_real_tcp_disconnect_removes_partial_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        listener, _, application, server, task = await running_server(tmp_path)
        port = listener.getsockname()[1]

        def interrupt_upload() -> None:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.putrequest("POST", "/audio/input")
            for name, value in upload_headers(1000).items():
                connection.putheader(name, value)
            connection.endheaders()
            connection.send(b"interrupted")
            connection.close()

        try:
            await asyncio.to_thread(interrupt_upload)
            for _ in range(100):
                jobs = await application.state.audio_upload_service.jobs.snapshot()
                if jobs and jobs[0].status.value == "failed":
                    break
                await asyncio.sleep(0.02)
            assert jobs and jobs[0].error == "upload_failed"
            assert not list(tmp_path.glob("*.part"))
            assert not list(tmp_path.glob("*.upload"))
        finally:
            server.should_exit = True
            await task
            listener.close()

    asyncio.run(scenario())
