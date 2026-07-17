# JARVIS ESP32 — Assistente de voz embarcado (áudio HTTP)

Projeto **concluído**: firmware ESP-IDF + backend Python para um assistente de
voz inspirado na Amazon Alexa, rodando em um **ESP32-WROOM DevKit** com
reprodução por um amplificador classe D e um pipeline de backend com fila de
áudio, streaming HTTP e transcrição de voz (STT).

## 1. Visão geral

O **JARVIS** reproduz, em hardware de baixo custo, o fluxo funcional de um
assistente de voz comercial como a linha Amazon Echo/Alexa: uma gravação de
voz é enviada ao sistema, processada e a resposta é reproduzida em um
alto-falante. Tudo roda em torno de um **ESP32-WROOM (Xtensa dual-core,
240 MHz, Wi-Fi 2,4 GHz)** para a etapa de reprodução, com um backend em Python
responsável por enfileirar, transmitir e transcrever o áudio.

Fluxo completo da entrega final:

```text
[gravação de voz no celular]
        |
        v
cliente/bot de envio (hospedado em uma Raspberry Pi)
        |
        v
POST /queue  ->  AudioQueue (backend FastAPI)
        |
        v
ESP32 faz GET /audio/stream  ->  buffer  ->  DAC (GPIO25)  ->  PAM8403  ->  alto-falante
```

Em paralelo, o backend expõe `POST /transcribe`, que usa **Whisper** para
transcrever qualquer gravação de voz recebida — a base de STT do assistente.

> A captura de voz **pelo próprio microfone do ESP32** (eletreto + LM358 →
> ADC) não foi o caminho de entrada usado nesta entrega. Em vez disso, o
> áudio de entrada é gravado externamente (no celular) e enviado por um
> cliente/bot hospedado em uma Raspberry Pi — essa escolha também satisfez o
> requisito da disciplina de ter um sensor vinculado a uma Raspberry Pi. Veja
> a seção [13](#13-decisões-de-projeto-e-possíveis-extensões) para o
> detalhamento dessa decisão e das extensões possíveis.

## 2. Hardware do projeto

| Componente | Função |
|---|---|
| **Microfone eletreto** | Transdutor acústico → sinal elétrico analógico de baixa amplitude |
| **Pré-amplificador LM358** | Amplificador operacional dual, condiciona o sinal do eletreto para a faixa de entrada do ADC do ESP32 |
| **ESP32-WROOM DevKit** | Microcontrolador principal: Wi-Fi e DAC interno (reprodução) |
| **PAM8403** | Amplificador de áudio classe D (saída em ponte/BTL) que alimenta o alto-falante a partir do DAC do ESP32 |
| **Alto-falante 8 Ω / 0,5 W** | Transdutor de saída, reproduz a resposta de voz |

### Ligação de saída (implementada e validada)

```text
ESP32 GPIO25 (DAC1) -- capacitor eletrolítico 10 µF -- PAM8403 L-IN
ESP32 GND ------------------------------------------ PAM8403 GND
fonte 5 V adequada ---------------------------------- PAM8403 VCC
alto-falante 8 Ω / 0,5 W ----------------------------- PAM8403 L+ e L-
```

Cuidados:

- o positivo do capacitor eletrolítico fica do lado do ESP32;
- **nunca** ligue `L-` ou `R-` do PAM8403 ao GND — a saída é em ponte (BTL);
- use um GND comum entre ESP32 e PAM8403;
- alimente o PAM8403 com uma fonte de 5 V própria, sem puxar toda a corrente
  do regulador de 3,3 V/5 V da placa ESP32;
- comece sempre com volume baixo (`AUDIO_VOLUME_PERCENT` no `menuconfig`)
  antes de subir o ganho.

## 3. Arquitetura do sistema

```text
┌───────────┐   grava   ┌────────────────────┐   POST /queue   ┌───────────────────┐
│  Celular  │──────────▶│ Cliente/bot de envio│───────────────▶│  Backend FastAPI   │
└───────────┘           │ (Raspberry Pi)      │                 │  (AudioQueue)      │
                         └────────────────────┘                 └─────────┬─────────┘
                                                                            │ GET /audio/stream
                                                                            v
                                                                  ┌───────────────────┐
                                                                  │ ESP32 (http_task + │
                                                                  │  playback_task)    │
                                                                  └─────────┬─────────┘
                                                                            │ DAC GPIO25
                                                                            v
                                                                  ┌───────────────────┐
                                                                  │ PAM8403 + alto-    │
                                                                  │ falante 8 Ω/0,5 W  │
                                                                  └───────────────────┘
```

Capacidade adicional, desacoplada desse caminho de reprodução:

```text
áudio (arquivo) -> POST /transcribe -> Whisper (STT) -> texto transcrito
```

## 4. Firmware: arquitetura FreeRTOS

O firmware (`main/http_audio_player.c`) roda sobre o FreeRTOS nativo do
ESP-IDF, sem o framework ESP-ADF:

```text
                         FREERTOS / ESP-IDF
┌──────────────────────────────────────────────────────────────────────┐
│   wifi_event_handler (callback) → seta/limpa WIFI_CONNECTED_BIT       │
│        |                                                               │
│        v                                                               │
│   ┌───────────────────┐        StreamBuffer         ┌───────────────┐ │
│   │   http_task        │  ──────(s_audio_buffer)────▶│ playback_task │ │
│   │  prioridade 5       │   PCM16 → DAC8 já convertido │ prioridade 6  │ │
│   └───────────────────┘                              └───────────────┘ │
│        |                                                     |          │
│        | GET HTTP (esp_http_client, timeout 35 s)             | dac_continuous_write()
│        v                                                     v          │
│   backend (Wi-Fi/TCP)                                 DAC interno (GPIO25)
└──────────────────────────────────────────────────────────────────────┘
```

### 4.1 `wifi_init()`

Cria um `EventGroupHandle_t` com o bit `WIFI_CONNECTED_BIT`, conecta ao Wi-Fi,
reconecta automaticamente em caso de queda e loga o IP obtido.

### 4.2 `dac_init()` — saída de áudio

Configura o driver `dac_continuous` no canal `DAC_CHANNEL_MASK_CH0` (GPIO25),
com `desc_num = 8`, buffer de 1024 amostras e clock `DAC_DIGI_CLK_SRC_APLL` na
taxa de `CONFIG_AUDIO_SAMPLE_RATE` (16 kHz por padrão). Como o DAC interno do
ESP32 clássico é de **8 bits sem sinal**, `pcm16_to_dac8()` converte cada
amostra PCM16 com sinal para essa faixa, aplicando o volume configurado.

### 4.3 `http_task` — recepção e conversão (prioridade 5)

1. Aguarda o bit de Wi-Fi conectado.
2. Faz `GET` para `CONFIG_AUDIO_STREAM_URL` com os headers `X-Audio-Format`,
   `X-Audio-Sample-Rate` e `X-Audio-Channels`, com **timeout de 35 segundos**
   (`HTTP_TIMEOUT_MS = 35000`) — ajustado propositalmente para exceder os 30 s
   de long-poll do backend, evitando que o firmware desista antes do backend
   responder. Essa relação é verificada automaticamente por um teste (ver
   seção 7).
3. Lê blocos de até 2048 bytes, converte PCM16 → DAC8 e envia ao
   `StreamBuffer`.
4. Reconecta a cada ~1 s após o fim do stream, erro ou queda de Wi-Fi.

### 4.4 `playback_task` — consumo e proteção contra cortes (prioridade 6)

1. Aguarda o **prebuffer** (`CONFIG_AUDIO_PREBUFFER_MS`, 250 ms) antes de
   tocar, escrevendo silêncio no DAC enquanto isso.
2. Consome o `StreamBuffer` e escreve direto no DAC via
   `dac_continuous_write()`.
3. Em caso de **underrun** (buffer vazio), registra o evento, volta a tocar
   silêncio e aguarda recompor o prebuffer.

### 4.5 Backpressure

O `StreamBuffer` tem capacidade fixa (~2 s por padrão,
`CONFIG_AUDIO_BUFFER_MS`). Quando `playback_task` consome mais devagar do que
`http_task` produz, o envio ao `StreamBuffer` bloqueia, o que naturalmente
reduz a velocidade de leitura do socket HTTP — e o próprio TCP aplica
backpressure ao backend. Nenhum chunk é descartado por causa disso.

## 5. Contrato do backend HTTP

O firmware **inicia** a conexão. Ele faz o equivalente a:

```http
GET /audio/stream HTTP/1.1
Host: 192.168.1.100:8000
Accept: application/octet-stream
X-Audio-Format: pcm_s16le
X-Audio-Sample-Rate: 16000
X-Audio-Channels: 1
```

O endpoint responde `200 OK`, `Content-Type: application/octet-stream` e
`Transfer-Encoding: chunked`, ou `Content-Length` quando o tamanho final já é
conhecido. O corpo é **PCM cru, sem cabeçalho WAV**:

| Parâmetro | Valor |
|---|---|
| Formato | PCM cru, sem cabeçalho WAV |
| Amostra | inteiro com sinal, 16 bits, little-endian (`s16le`) |
| Canais | 1 (mono) |
| Taxa de amostragem | 16.000 Hz (configurável) |
| Content-Type | `application/octet-stream` |

Cada segundo de áudio ocupa `16.000 × 2 = 32.000 bytes`. Blocos de 20 a
100 ms (640 a 3.200 bytes) funcionam bem; o backend de referência usa 1.280
bytes (40 ms). **Nunca envie** WAV com cabeçalho, MP3, AAC, Opus, Base64,
JSON, áudio estéreo ou amostras `float`.

## 6. Backend (FastAPI)

O backend está implementado em `backend/` com a seguinte estrutura:

```text
backend/
├── main.py                          # uvicorn.run("app:create_app", factory=True)
├── app.py                           # cria o FastAPI e o AudioQueue singleton
├── routes/audio.py                  # POST /queue, GET /audio/stream, GET /health, POST /transcribe
├── services/audio_queue.py          # fila de "último valor" com long-poll e backpressure
├── services/stt/
│   ├── transcription_service.py     # interface Transcriber + TranscriptionService
│   ├── whisper_transcriber.py       # implementação com openai-whisper (modelo "base")
│   └── faster_whisper_transcriber.py # esqueleto para uma futura otimização com faster-whisper
├── services/tts/                    # pacote reservado para o serviço de síntese de voz
├── models/                          # AudioChunk = bytes
├── utils/pcm.py                     # validate_pcm(), strip_wav_header()
├── uploads/arquivo.mp3              # amostra usada em testes manuais de transcrição
└── tests/                           # pytest (fila, rotas, PCM, integração com o firmware)
```

### 6.1 Endpoints

| Endpoint | Método | Descrição |
|---|---|---|
| `/queue` | `POST` | Recebe PCM cru **ou** WAV (o cabeçalho é removido automaticamente), valida e enfileira. Responde `202 {"status": "queued", "bytes": N}`; `400` se o payload for inválido. |
| `/audio/stream` | `GET` | Aguarda áudio disponível por até 30 s (long-poll) e transmite em chunks. `204` se não houver áudio; `409` se já houver outro consumidor ativo. |
| `/health` | `GET` | Retorna `status`, `audio_ready` (há áudio pendente?) e `stream_active` (há um stream em andamento?). |
| `/transcribe` | `POST` | Recebe `{"audio_path": "..."}`, transcreve o arquivo com Whisper e retorna `{"status": "success", "text": "..."}`. `404`/`500` em caso de erro. |

### 6.2 `AudioQueue` — fila de "último valor"

- `enqueue(pcm)` guarda o áudio pendente; um novo `enqueue` **substitui** o
  anterior — o mais recente vence;
- `consume(chunk_size=1280)` é um generator assíncrono: reserva o consumidor
  antes do long-poll (evitando corrida entre dois clientes esperando a fila
  vazia ao mesmo tempo), aguarda até 30 s por áudio, entrega em blocos e cede
  o controle a cada chunk (`await asyncio.sleep(0)`);
- se o consumidor desconectar no meio do stream, o áudio **não é perdido** —
  a próxima conexão reentrega o mesmo conteúdo, a menos que um novo `enqueue`
  já tenha substituído o payload;
- duas conexões simultâneas em `/audio/stream` não são permitidas: a segunda
  recebe `409 Conflict`.

### 6.3 STT com Whisper

`WhisperTranscriber` carrega o modelo `base` do `openai-whisper` uma única vez
na inicialização e implementa a interface `Transcriber`
(`transcribe(audio_path) -> str`). Essa camada é independente das rotas HTTP e
do `AudioQueue`, o que permite trocar o motor de STT (por exemplo, para
`faster-whisper`, cujo esqueleto já existe em
`faster_whisper_transcriber.py`) sem alterar `routes/audio.py`.

## 7. Testes automatizados

```bash
cd backend
pytest -v
```

A suíte cobre:

- **`test_audio_queue.py`** — enfileiramento/consumo, bloqueio até chegar
  áudio, rejeição de um segundo consumidor simultâneo, substituição do áudio
  pendente, preservação do áudio após desconexão, respeito ao `chunk_size`,
  áudio grande, `peek()`.
- **`test_pcm.py`** — validação de PCM par/ímpar e extração do chunk `data`
  de um WAV com chunks intermediários.
- **`test_routes.py`** — todos os endpoints via `httpx.ASGITransport`,
  incluindo o caso de WAV enviado ao `/queue` e o conflito `409`.
- **`test_firmware_integration.py`** — o teste mais importante para a
  integração hardware/software: sobe um servidor Uvicorn real, lê o próprio
  código-fonte `main/http_audio_player.c` para confirmar que
  `HTTP_TIMEOUT_MS` é maior que os 30 s de long-poll do backend, e faz uma
  requisição HTTP real reproduzindo exatamente os headers e o tamanho de
  leitura (2048 bytes) usados pelo firmware — validando o contrato completo
  sem precisar do hardware físico.

## 8. Preparando o ambiente (ESP-IDF)

Alvo fixado em **ESP-IDF v5.5.4**, alvo **esp32** (ESP32-WROOM clássico — não
use ESP32-C3/S3, que não têm o DAC interno usado pela saída de áudio).

### Windows (fluxo usado neste repositório)

1. Instale o **ESP-IDF Tools Installer** (v5.5.4) — ele usa o
   `eim_config.toml` da raiz do projeto como referência (caminhos em
   `C:\Espressif`, Python 3.13, toolchain Xtensa, OpenOCD, ccache).
2. Abra o terminal **"ESP-IDF 5.5 CMD"** (ou rode `export.bat`) para ativar o
   ambiente.
3. Confirme com `idf.py --version`.

### Linux / macOS

```bash
git clone -b v5.5.4 --recursive https://github.com/espressif/esp-idf.git ~/esp/esp-idf
cd ~/esp/esp-idf
./install.sh esp32
. ./export.sh
idf.py --version
```

## 9. Compilando e gravando o firmware

### 9.1 Teste isolado de hardware (sem Wi-Fi/backend)

```powershell
cd examples\star_wars_test
idf.py set-target esp32
idf.py build
idf.py -p COMx flash monitor
```

### 9.2 Player HTTP completo

```powershell
idf.py set-target esp32
idf.py menuconfig
```

No menu **`HTTP audio player`**, configure:

| Campo | Valor sugerido |
|---|---|
| Wi-Fi SSID / password | credenciais da rede 2,4 GHz |
| HTTP PCM stream URL | `http://<IP-do-backend>:8000/audio/stream` |
| PCM sample rate | `16000` |
| Output volume | começar entre `30` e `55` |
| Audio buffer capacity | `2000` ms |
| Prebuffer before playback | `250` ms |

```powershell
idf.py build
idf.py -p COMx flash monitor
```

## 10. Executando o backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

O servidor escuta em `0.0.0.0:8000`. Configure o firmware com
`http://IP_DO_COMPUTADOR:8000/audio/stream` e libere a porta 8000 no firewall.

Para enfileirar áudio manualmente:

```powershell
curl.exe -X POST --data-binary "@resposta.pcm" http://localhost:8000/queue
```

Uploads WAV também são aceitos — o backend extrai automaticamente o chunk
`data`. Para transcrever um arquivo já salvo no servidor:

```bash
curl -X POST http://localhost:8000/transcribe \
     -H "Content-Type: application/json" \
     -d '{"audio_path": "uploads/arquivo.mp3"}'
```

Se o TTS gerar WAV/MP3, converta para PCM cru antes de enfileirar:

```bash
ffmpeg -i resposta.wav -f s16le -acodec pcm_s16le -ac 1 -ar 16000 resposta.pcm
```

## 11. Validação ponta a ponta (como foi testado)

A entrega foi validada com um fluxo real, fora do laboratório:

1. Uma gravação de voz é feita em um celular.
2. O arquivo é enviado por um cliente/bot (hospedado em uma Raspberry Pi) que
   encaminha o áudio para o backend.
3. O backend recebe o arquivo, responde `HTTP 202` confirmando o
   recebimento, e o áudio fica disponível para a ESP32.
4. A ESP32, já em execução e conectada ao Wi-Fi, busca o áudio via
   `GET /audio/stream` e o reproduz pelo alto-falante ligado ao PAM8403.

Hospedar o backend em uma Raspberry Pi conectada à rede também atendeu ao
requisito da disciplina de manter um sensor/dispositivo vinculado a uma
Raspberry Pi.

## 12. Mensagens do monitor serial / troubleshooting

| Mensagem | Significado |
|---|---|
| `Wi-Fi conectado, IP=...` | conexão com a rede concluída |
| `stream conectado: ... (chunked)` | backend respondeu `200`, stream aberto |
| `playback iniciado com N ms no buffer` | prebuffer atingido, reprodução começou |
| `buffer vazio (underrun N)` | rede entregou áudio mais devagar que o consumo; ESP32 volta a aguardar prebuffer |
| `backend respondeu HTTP ...` | endpoint retornou status diferente de 200 |
| `erro de leitura HTTP` | conexão caiu ou houve erro de socket |
| `fim do stream HTTP` | backend terminou corretamente a resposta |
| `Wi-Fi desconectado; tentativa X/10` | reconexão automática em andamento |

Checklist rápido do backend antes de testar:

- [ ] endpoint acessível pelo IP da rede local (ou da Raspberry Pi);
- [ ] resposta `200 OK`, corpo binário (sem JSON/Base64);
- [ ] PCM cru `s16le`, mono, 16 kHz, sem cabeçalho WAV;
- [ ] firewall liberando a porta 8000.

## 13. Decisões de projeto e possíveis extensões

**Por que a entrada de voz não usa o microfone do ESP32 nesta entrega?** O
hardware de captura (eletreto + LM358) foi definido para uso futuro com o ADC
contínuo do ESP32, mas o firmware atual implementa apenas o caminho de
**reprodução** (DAC + PAM8403). Para a entrega final, a captura de voz foi
resolvida gravando no celular e enviando por um cliente/bot hospedado em uma
Raspberry Pi — o que também cobriu o requisito de sensor vinculado à
Raspberry Pi, evitando duplicar esforço de infraestrutura.

Extensões possíveis, caso o projeto continue depois desta entrega:

- **Captura nativa pelo ESP32:** implementar `adc_continuous` para o par
  eletreto + LM358, com uma máquina de estados que alterne entre gravação e
  reprodução (ambas usam o periférico I2S0 do ESP32 clássico, que não pode
  operar nos dois sentidos ao mesmo tempo).
- **TTS integrado:** o pacote `services/tts/` já está reservado; falta
  plugar um provedor de síntese de voz e converter a saída para PCM s16le
  mono 16 kHz antes de `AudioQueue.enqueue()`.
- **LLM para gerar respostas:** hoje o `/transcribe` apenas converte voz em
  texto; um serviço de LLM poderia consumir esse texto e gerar a resposta
  que o TTS sintetizaria.
- **`faster-whisper`:** já há um esqueleto em
  `faster_whisper_transcriber.py` para trocar o motor de STT por uma opção
  mais rápida, sem alterar as rotas.

## 14. Sobre o ThingsBoard

Este projeto **não integra o ThingsBoard** — nenhum arquivo do firmware, do
backend ou da documentação faz referência a ele. Se o dashboard de telemetria
for desejado no futuro, o caminho mais simples seria publicar periodicamente
métricas do backend (fila, stream ativo, contagem de transcrições) em um
tópico MQTT `v1/devices/me/telemetry` de uma instância do ThingsBoard, sem
alterar o firmware ou o contrato de áudio HTTP descrito na seção 5.

## 15. Referências

- ZHANG, Y.; SUDA, N.; LAI, L.; CHANDRA, V. *Hello Edge: Keyword Spotting on
  Microcontrollers*. arXiv:1711.07128, 2017.
- CERUTTI, G. et al. *Sub-mW Keyword Spotting on an MCU*. arXiv:2201.03386,
  2022.
- LI, Y.; KIM, S.; SY, E. *A survey on Amazon Alexa attack surfaces*.
  arXiv:2102.11442, 2021.
