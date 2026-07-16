import asyncio

import httpx
import pytest

from config import AudioInputConfig
from services.llm_service import (
    AIProviderNotConfigured,
    DeepSeekChatLLMService,
    LLMProviderError,
)
from services.tts_service import OpenAISpeechTTSService


def config() -> AudioInputConfig:
    return AudioInputConfig(
        device_token="device",
        llm_api_key="secret-test-key",
        llm_base_url="https://provider.test/v1",
        tts_api_key="secret-tts-key",
        tts_base_url="https://provider.test/v1",
        llm_model="test-llm",
        tts_model="test-tts",
        tts_voice="test-voice",
    )


def test_deepseek_service_extracts_text_without_logging_content(caplog) -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer secret-test-key"
            document = __import__("json").loads(request.content)
            assert document["model"] == "test-llm"
            assert document["messages"][1] == {
                "role": "user",
                "content": "transcricao muito privada",
            }
            assert document["thinking"] == {"type": "disabled"}
            assert document["max_tokens"] == 200
            assert document["stream"] is False
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Resposta curta.",
                            }
                        }
                    ]
                },
            )

        client = httpx.AsyncClient(
            base_url="https://provider.test/v1/",
            transport=httpx.MockTransport(handler),
        )
        service = DeepSeekChatLLMService(config(), client=client)
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
        service = DeepSeekChatLLMService(config(), client=client)
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
        DeepSeekChatLLMService(missing)
    with pytest.raises(AIProviderNotConfigured):
        OpenAISpeechTTSService(missing)


def test_llm_and_tts_credentials_are_loaded_separately(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    loaded = AudioInputConfig.from_env()
    assert loaded.llm_api_key == "deepseek-test-key"
    assert loaded.tts_api_key == "openai-test-key"
    assert loaded.llm_base_url == "https://api.deepseek.com"
    assert loaded.tts_base_url == "https://api.openai.com/v1"
    assert loaded.tts_model == "gpt-4o-mini-tts"
