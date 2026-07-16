"""Smoke test opt-in da credencial e do contrato real da DeepSeek."""

import asyncio
import os

import pytest

from config import AudioInputConfig
from services.llm_service import DeepSeekChatLLMService


@pytest.mark.provider
@pytest.mark.skipif(
    os.getenv("RUN_REAL_DEEPSEEK") != "1",
    reason="defina RUN_REAL_DEEPSEEK=1 para chamar a API real",
)
def test_deepseek_returns_a_short_response() -> None:
    async def scenario() -> None:
        service = DeepSeekChatLLMService(AudioInputConfig.from_env())
        try:
            response = await service.generate(
                "Confirme em uma frase curta que a integração está funcionando."
            )
            assert response.strip()
            assert len(response) <= 1000
        finally:
            await service.aclose()

    asyncio.run(scenario())
