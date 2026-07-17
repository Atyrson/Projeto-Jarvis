# Memória de trabalho do projeto

Este arquivo registra informações duráveis para retomar a implementação em
interações futuras. Atualizá-lo sempre que mudar ambiente, arquitetura,
contratos, decisões importantes ou progresso das fases.

## Objetivo atual

Executar `backend/PLANO_IMPLEMENTACAO_AUDIO_CELULAR.md`: o celular grava e
envia o arquivo cru para a ESP32, a ESP32 encaminha progressivamente ao
backend, e o pipeline STT → LLM → TTS devolve PCM s16le mono 16 kHz ao player.

## Git

- Branch de implementação: `feature/audio-celular-esp32`.
- Branch base e commit inicial: `main` em `21b6c4a`.
- Usar commits incrementais por implementação e auditoria de cada fase.
- O plano, os diários e evidências são versionados em `backend/auditoria/`.

### Commits concluídos

- `1451864` — integração do STT com carga no lifespan e execução fora do event loop.
- `7010599` — auditoria da Fase 0 e versionamento do plano.
- `9b384aa` — upload progressivo no backend.
- `7e068b1` — auditoria da Fase 1.
- `8fbfd35` — criação deste arquivo de memória operacional.
- `b3e07fe` — página móvel, servidor web e proxy de upload da ESP32.
- `23244a4` — auditoria das Fases 2 e 3.
- `3e14e9a` — FFmpeg/ffprobe, normalização e integração real com Whisper.
- `701ec5a` — auditoria da Fase 4.
- `2b387cc` — serviços LLM/TTS e pipeline completo.
- `8f62b9d` — teste do PCM final por `/audio/stream`.
- `a569aaf` — auditoria do pipeline LLM/TTS.
- `b94a46e` — limpeza, retenção, shutdown, carga e observabilidade.
- `6557157` — integração DeepSeek Chat Completions como LLM.
- `c3f0f16` — contrato, smoke test opt-in e documentação da DeepSeek.
- `6f06aa5` — auditoria final da robustez e validação de software.
- `ea91026` — modelo TTS padrão migrado para `gpt-4o-mini-tts`.
- `2754975` — log Wi-Fi passa a mostrar código e nome da desconexão.

## Ambiente local

- Sistema: Windows/PowerShell.
- Python do backend: `C:\tmp\python312\python.exe` (Python 3.12.4).
- Requirements instalados a partir de `backend/requirements.txt`.
- Torch: 2.13.0+cpu; openai-whisper: 20250625.
- `python` não está no `PATH`; usar sempre o caminho absoluto acima.
- FFmpeg/ffprobe 8.1.2 portáteis: `C:\tmp\ffmpeg\ffmpeg-8.1.2-essentials_build\bin`.
- Modelo Whisper base em cache: `C:\tmp\whisper-cache`.
- Variáveis úteis: `FFMPEG_BIN`, `FFPROBE_BIN` e `STT_MODEL_DIR`.
- ESP-IDF: 5.5.4 em `C:\Espressif\v5.5.4\esp-idf`.
- Perfil IDF: `C:\Espressif\tools\Microsoft.v5.5.4.PowerShell_profile.ps1`.
- O perfil exige PowerShell com `-ExecutionPolicy Bypass` e acesso fora do sandbox,
  pois seu venv referencia o Python 3.13 da Microsoft Store.
- O diretório `build` antigo usa outro Python. Para não apagá-lo, o build desta
  implementação usa `build-audio-cellular`.

## Comandos reproduzíveis

### Testes do backend

Executar dentro de `backend`:

```powershell
& 'C:\tmp\python312\python.exe' -m pytest tests -q --basetemp .pytest_tmp
```

O `--basetemp` precisa ficar dentro do workspace; o temp padrão em `AppData`
é bloqueado pelo sandbox. Remover `.pytest_tmp` após validar, confirmando antes
que o caminho resolvido permanece dentro de `backend`.

### Build do firmware

Ativar o perfil IDF em um PowerShell com bypass e executar:

```powershell
idf.py -B build-audio-cellular build
```

## Progresso funcional

- Fase 0 concluída: STT injetável, modelo carregado uma vez no lifespan,
  `asyncio.to_thread()` e limite de concorrência. `/transcribe` permanece
  diagnóstico temporário.
- Fase 1 concluída: `POST /audio/input`, `GET /audio/input/{job_id}`,
  autenticação por token, allowlist MIME, limite, `.part`, SHA-256 incremental,
  promoção para `.upload`, limpeza e um upload concorrente.
- Após a Fase 1: 41 testes passavam.
- Fases 2–3 concluídas em software: página móvel, servidor HTTP da ESP32 e
  proxy de 4 KiB; build ESP-IDF aprovado com imagem de 920.048 bytes.
- Após as Fases 2–3: 45 testes passavam.
- Fase 4 concluída: WAV e MP3 normalizam para mono 16 kHz; teste real do
  Whisper base aprovado. Suíte rápida: 53 testes; teste real: 1.
- Fase 5 concluída em software: DeepSeek Chat Completions para LLM e OpenAI
  Speech API para TTS, com credenciais separadas; pipeline até
  `/audio/stream`.
- Fase 6 concluída em software: cleanup e retenção periódicos, cancelamento no
  shutdown, eventos correlacionados, testes TCP de fragmentação/desconexão e
  teste de carga. Suíte final: 68 aprovados; Whisper real: 1 aprovado.
- Fluxo físico ponta a ponta validado em 2026-07-16: celular enviou 88.726 bytes
  pela ESP32, backend respondeu `202`, Whisper, DeepSeek e OpenAI TTS concluíram,
  e o PCM retornou à ESP32. A falha Wi-Fi anterior era hotspot em 5 GHz; o ESP32
  conectou após configurar o hotspot em 2,4 GHz.
- A chave DeepSeek foi fornecida na conversa, mas não foi gravada no repositório,
  arquivo local, comando ou log. Para usá-la, exportar `DEEPSEEK_API_KEY` no
  processo. O smoke test real exige também `RUN_REAL_DEEPSEEK=1`.
- O TTS requer outra credencial em `OPENAI_API_KEY`; a chave DeepSeek não deve
  ser reutilizada para TTS.
- Modelo TTS padrão: `gpt-4o-mini-tts` via `POST /v1/audio/speech`; pode ser
  sobrescrito por `TTS_MODEL`.
- MCP oficial de documentação registrado globalmente como `openaiDeveloperDocs`;
  uma nova sessão pode ser necessária para expor suas ferramentas.

## Contratos e decisões que não devem regredir

- O navegador envia o objeto `File` diretamente; sem multipart, Base64,
  `FileReader` ou `arrayBuffer()`.
- Uma gravação corresponde a uma única requisição celular → ESP32 e uma única
  requisição ESP32 → backend.
- A ESP32 reutiliza buffer fixo; não acumula a gravação em RAM.
- O backend usa `request.stream()`, nunca `request.body()` em `/audio/input`.
- Nome enviado pelo celular é apenas metadado; caminhos são gerados pelo backend.
- O token existe somente entre ESP32 e backend e nunca entra no HTML ou logs.
- Não registrar áudio, token, texto integral de STT, prompt ou resposta integral.
- Saída final do pipeline: PCM s16le, mono, 16 kHz, validado antes de
  `AudioQueue.enqueue()`.
- Preservar compatibilidade de `/queue`, `/audio/stream` e `/health`.
- LLM padrão: `deepseek-v4-flash` via `https://api.deepseek.com/chat/completions`,
  com `thinking` desabilitado para reduzir latência da resposta falada.
- Desconexões Wi-Fi do firmware registram `reason=<código> (<nome>)`; usar esse
  par para distinguir AP ausente, autenticação, handshake e segurança incompatível.

## Pendências de validação física

- Repetir o teste no segundo sistema móvel (Android ou iOS) ainda não utilizado.
- Logs seriais, heap mínimo/inicial/final e desconexão durante upload.
