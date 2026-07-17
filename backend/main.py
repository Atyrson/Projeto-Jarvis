"""Entrypoint do servidor de desenvolvimento/producao simples."""

import uvicorn


if __name__ == "__main__":
    # `app:app` usa a instância criada com `load_stt=True`. Executar a fábrica
    # diretamente usaria o padrão `load_stt=False` e deixaria o pipeline real
    # de STT -> LLM -> TTS indisponível.
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
