import asyncio

import httpx
import pytest

from config import AudioInputConfig
from services.llm_service import (
    AIProviderNotConfigured,
    LLMProviderError,
    OpenAIResponsesLLMService,
)
from services.tts_service import OpenAISpeechTTSService


def config() -> AudioInputConfig:
    return AudioInputConfig(
        device_token="device",
        ai_api_key="secret-test-key",
        ai_base_url="https://provider.test/v1",
        llm_model="test-llm",
        tts_model="test-tts",
        tts_voice="test-voice",
    )


def test_responses_service_extracts_text_without_logging_content(caplog) -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/responses"
            assert request.headers["authorization"] == "Bearer secret-test-key"
            document = __import__("json").loads(request.content)
            assert document["model"] == "test-llm"
            assert document["input"] == "transcricao muito privada"
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "Resposta curta."}
                            ],
                        }
                    ]
                },
            )

        client = httpx.AsyncClient(
            base_url="https://provider.test/v1/",
            transport=httpx.MockTransport(handler),
        )
        service = OpenAIResponsesLLMService(config(), client=client)
        assert await service.generate("transcricao muito privada") == "Resposta curta."
        await client.aclose()
        assert "transcricao muito privada" not in caplog.text
        assert "secret-test-key" not in caplog.text

    asyncio.run(scenario())


def test_speech_service_returns_wav_bytes() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/audio/speech"
            document = __import__("json").loads(request.content)
            assert document == {
                "model": "test-tts",
                "voice": "test-voice",
                "input": "Resposta curta.",
                "response_format": "wav",
            }
            return httpx.Response(200, content=b"RIFF-fake-wav")

        client = httpx.AsyncClient(
            base_url="https://provider.test/v1/",
            transport=httpx.MockTransport(handler),
        )
        service = OpenAISpeechTTSService(config(), client=client)
        assert await service.synthesize("Resposta curta.") == b"RIFF-fake-wav"
        await client.aclose()

    asyncio.run(scenario())


def test_provider_error_hides_remote_body(caplog) -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="remote secret body")

        client = httpx.AsyncClient(
            base_url="https://provider.test/v1/",
            transport=httpx.MockTransport(handler),
        )
        service = OpenAIResponsesLLMService(config(), client=client)
        with pytest.raises(LLMProviderError) as error:
            await service.generate("private input")
        assert error.value.error_code == "llm_failed"
        assert "remote secret body" not in caplog.text
        assert "private input" not in caplog.text
        await client.aclose()

    asyncio.run(scenario())


def test_api_key_is_required() -> None:
    missing = AudioInputConfig(device_token="device")
    with pytest.raises(AIProviderNotConfigured):
        OpenAIResponsesLLMService(missing)
    with pytest.raises(AIProviderNotConfigured):
        OpenAISpeechTTSService(missing)
