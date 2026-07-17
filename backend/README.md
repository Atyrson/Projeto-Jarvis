# Backend de áudio para ESP32

Servidor FastAPI para o fluxo completo de voz:

```text
celular -> ESP32 -> POST /audio/input -> FFmpeg -> Whisper -> LLM -> TTS
        -> PCM s16le mono 16 kHz -> AudioQueue -> GET /audio/stream -> ESP32
```

O upload é escrito progressivamente em disco. O nome enviado pelo celular é
somente metadado; caminhos reais são gerados pelo backend. Áudio, token,
transcrição e conteúdo dos provedores não são registrados em logs.

## Ambiente

- Python 3.10 ou superior;
- FFmpeg e ffprobe;
- modelo Whisper configurado;
- token compartilhado com a ESP32;
- chave DeepSeek para LLM e chave OpenAI separada para TTS no pipeline real.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env.local
```

O FastAPI não carrega `.env.local` automaticamente. Exporte as variáveis no
serviço/processo ou use seu gerenciador de segredos. Nunca preencha e versione o
arquivo de exemplo. As opções estão documentadas em `.env.example`.

No ambiente de desenvolvimento usado nesta implementação, Python e FFmpeg são
portáteis. Um exemplo de execução é:

```powershell
$env:AUDIO_INPUT_DEVICE_TOKEN='defina-fora-do-git'
$env:FFMPEG_BIN='C:\tmp\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe'
$env:FFPROBE_BIN='C:\tmp\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffprobe.exe'
$env:STT_MODEL_DIR='C:\tmp\whisper-cache'
$env:DEEPSEEK_API_KEY='defina-no-ambiente-seguro'
$env:OPENAI_API_KEY='defina-no-ambiente-seguro'
& 'C:\tmp\python312\python.exe' main.py
```

O LLM usa por padrão `https://api.deepseek.com/chat/completions` com
`deepseek-v4-flash`. O TTS usa a Speech API da OpenAI com o modelo padrão
`gpt-4o-mini-tts`. As credenciais são independentes: nunca use
`DEEPSEEK_API_KEY` como chave do TTS. O arquivo
`.env.local` é ignorado pelo Git, mas o processo não o carrega automaticamente.

## Endpoints

- `POST /audio/input`: corpo binário cru encaminhado pela ESP32; exige
  `Content-Length`, `Content-Type`, `X-Request-Id`, `X-Source-Device: esp32`,
  `X-Device-Id` e `X-Device-Token`. Responde `202` após validar o upload.
- `GET /audio/input/{job_id}`: estado `receiving`, `accepted`, `converting`,
  `stt`, `llm`, `tts`, `queued` ou `failed`.
- `GET /audio/stream`: long-poll da ESP32 para PCM s16le mono 16 kHz.
- `POST /queue`: compatibilidade para enfileirar PCM/WAV diretamente.
- `GET /health`: saúde e estado da fila/stream.
- `POST /transcribe`: diagnóstico temporário do STT; não é usado pelo pipeline.

O token é obrigatório para o caminho de entrada. Se não estiver configurado,
`POST /audio/input` responde `503` sem iniciar escrita ou IA.

## Testes

```powershell
python -m pytest tests -q -m "not stt"
```

Em ambientes restritos, direcione temporários para o workspace:

```powershell
& 'C:\tmp\python312\python.exe' -m pytest tests -q -m "not stt" --basetemp .pytest_tmp -p no:cacheprovider
```

O smoke test real do Whisper é separado:

```powershell
$env:RUN_REAL_STT='1'
$env:STT_MODEL_DIR='C:\tmp\whisper-cache'
python -m pytest tests\test_stt_real.py -q -m stt
```

O smoke test da DeepSeek realiza uma chamada cobrada e só roda explicitamente:

```powershell
$env:DEEPSEEK_API_KEY='defina-no-ambiente-seguro'
$env:RUN_REAL_DEEPSEEK='1'
python -m pytest tests\test_deepseek_real.py -q -m provider
```

A suíte inclui unidades, ASGI, provedores HTTP simulados, TCP real fragmentado,
interrupção de upload, limpeza/retenção, pipeline completo com fakes e contrato
do firmware.
