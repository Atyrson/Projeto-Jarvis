# Fase 5 — LLM, TTS e retorno ao player

## Identificação

- Data/hora inicial: 2026-07-16T19:16:10-03:00
- Data/hora final: 2026-07-16T19:27:00-03:00
- Branch: `feature/audio-celular-esp32`
- Commit inicial: `701ec5a`
- Commits finais da implementação: `2b387cc` e `8f62b9d`
- Responsável: Codex, sob solicitação do proprietário do repositório

## Objetivo

Continuar após STT, gerar resposta textual e áudio, converter para PCM s16le
mono 16 kHz, validar e enfileirar para `/audio/stream`.

## Estado encontrado antes da alteração

O pipeline terminava após a transcrição. Não havia interfaces LLM/TTS,
provedores, configuração de credencial, orquestração final ou cleanup no sucesso.

## Arquivos criados, alterados e removidos

- Criados: `services/llm_service.py`, `services/tts_service.py` e
  `tests/test_ai_services.py`.
- Alterados: `app.py`, `config.py`, `services/audio_pipeline.py` e testes do
  pipeline.
- Nenhum arquivo removido.

## Decisões tomadas e justificativas

- Interfaces `LLMService` e `TTSService` aceitam fakes ou outros provedores.
- A implementação real usa HTTPX com Responses API e Speech API, confirmadas na
  documentação oficial atual da OpenAI.
- Chave vem apenas de `OPENAI_API_KEY`; base URL, modelos, voz e timeouts são
  configuráveis por ambiente.
- Sem chave, serviços explícitos marcam o job como `ai_not_configured`; a
  aplicação não contém fallback inseguro nem segredo padrão.
- Prompt, transcrição e resposta nunca entram nos logs; somente contagens.
- Nenhum PCM é enfileirado antes de todas as etapas terminarem e passarem por
  `validate_pcm()`.

## Comandos executados

- Registro do MCP oficial: `codex mcp add openaiDeveloperDocs --url https://developers.openai.com/mcp`.
- Consulta restrita à documentação oficial após o MCP exigir nova sessão.
- `pytest tests -q -m "not stt" --basetemp .pytest_tmp -p no:cacheprovider`.

## Testes executados

- 60 aprovados, 1 teste STT real separado, 6,33 s.
- MockTransport valida URLs, headers, corpos e respostas dos dois provedores.
- Pipeline fake valida STT → LLM → TTS → PCM → `/audio/stream`.

## Evidências

- Resposta PCM esperada no teste ponta a ponta: 4 bytes válidos e idênticos no
  endpoint `/audio/stream`.
- Conversão real FFmpeg de WAV 24 kHz para PCM 16 kHz: 3.200 bytes, já coberta
  pela Fase 4 e reutilizada pelo pipeline.
- Testes confirmam ausência da chave, transcrição, resposta e corpo remoto nos logs.
- Provedor real não foi chamado porque `OPENAI_API_KEY` não estava presente.

## Desvios em relação ao plano

O teste com provedores reais não foi executado por ausência de credencial. Os
contratos foram validados integralmente com HTTP simulado, sem inventar uma
chave ou realizar cobrança sem autorização.

## Riscos e pendências

- Executar um caso real controlado quando uma chave de bancada for fornecida.
- Rever modelo/voz por ambiente, pois aliases de serviço evoluem.
- Capturar reprodução física pela ESP32 depois de configurar rede e token.

## Critérios de conclusão

- [x] Interfaces e implementações LLM/TTS existem.
- [x] Segredos e opções vêm do ambiente.
- [x] Pipeline continua após STT e converte para PCM mono 16 kHz.
- [x] PCM é validado e entregue por `/audio/stream`.
- [x] Falha não enfileira payload parcial e limpa temporários.
- [x] Provedores falsos cobrem o fluxo completo.
- [ ] Provedores reais foram executados com credencial de bancada.
- [ ] Reprodução física foi capturada no log serial.

## Resultado final

O pipeline completo funciona de forma reproduzível com contratos reais
simulados e saída PCM compatível; validações com cobrança e hardware permanecem
explicitamente pendentes de credencial/configuração externa.
