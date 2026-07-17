# JARVIS ESP32 — assistente de voz com entrada pelo celular

Projeto de assistente de voz que integra firmware ESP-IDF, um ESP32-WROOM,
backend Python e provedores de IA. O fluxo completo foi validado em hardware:
o usuário grava no celular, a ESP32 encaminha o arquivo ao backend, o áudio é
transcrito, uma resposta é gerada e a voz sintetizada é reproduzida pelo
alto-falante conectado à ESP32.

Vídeo de Apresentação: https://youtu.be/wqMMu-LJyuo

## 1. Fluxo final implementado

```text
Celular abre a página servida pela ESP32
        |
        | POST /api/audio/input
        v
ESP32 faz proxy progressivo do upload
        |
        | POST /audio/input
        v
Backend FastAPI
        |
        +--> FFmpeg/ffprobe: valida e normaliza o arquivo
        +--> Whisper base: voz -> texto
        +--> DeepSeek: texto -> resposta
        +--> OpenAI gpt-4o-mini-tts: resposta -> voz
        +--> FFmpeg: voz -> PCM s16le, mono, 16 kHz
        +--> AudioQueue
                 |
                 | GET /audio/stream
                 v
ESP32 -> StreamBuffer -> DAC GPIO25 -> PAM8403 -> alto-falante

O microfone eletreto e o LM358 permanecem como extensão futura. Nesta versão,
a captura é feita pelo celular e a reprodução é feita pela ESP32.

## 2. Componentes

### Hardware usado na reprodução

| Componente | Função |
|---|---|
| ESP32-WROOM DevKit | Wi-Fi, servidor web, proxy HTTP, streaming e DAC interno |
| PAM8403 | Amplifica a saída do DAC para o alto-falante |
| Alto-falante 8 Ω / 0,5 W | Reproduz a resposta sintetizada |
| Capacitor eletrolítico 10 µF | Acoplamento entre o DAC e a entrada do amplificador |

### Software e serviços

| Componente | Responsabilidade |
|---|---|
| ESP-IDF 5.5.4 / FreeRTOS | Firmware do ESP32 |
| FastAPI / Uvicorn | API e processamento assíncrono no backend |
| FFmpeg e ffprobe | Inspeção e normalização dos formatos recebidos |
| OpenAI Whisper `base` | Transcrição local de voz para texto |
| DeepSeek | Geração da resposta textual |
| OpenAI `gpt-4o-mini-tts` | Síntese da resposta em voz |

## 3. Pré-requisitos

- ESP32 clássico com DAC interno, como ESP32-WROOM DevKit;
- rede Wi-Fi **2,4 GHz** — o ESP32 usado não se conecta a redes somente 5 GHz;
- ESP-IDF **v5.5.4**, com alvo `esp32`;
- Python 3.10 ou superior; a implementação foi validada com Python 3.12;
- FFmpeg e ffprobe disponíveis no `PATH` ou configurados por caminho absoluto;
- chave da DeepSeek para o LLM;
- chave da OpenAI para o TTS;
- celular, ESP32 e computador do backend acessíveis pela mesma rede local.

Antes de continuar, confirme:

```powershell
python --version
ffmpeg -version
ffprobe -version
idf.py --version
```

## 4. Preparação do backend no Windows

No PowerShell:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env.local
```

Se o PowerShell bloquear a ativação do ambiente virtual, use apenas nesta
sessão:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.venv\Scripts\Activate.ps1
```

### 4.1 Variáveis obrigatórias

Edite `backend/.env.local` e preencha pelo menos:

```dotenv
AUDIO_INPUT_DEVICE_TOKEN=escolha-um-token-local-forte
DEEPSEEK_API_KEY=sua-chave-deepseek
OPENAI_API_KEY=sua-chave-openai
```

O valor de `AUDIO_INPUT_DEVICE_TOKEN` deve ser exatamente igual ao campo
`Backend device token` do `idf.py menuconfig`.

Se FFmpeg e ffprobe não estiverem no `PATH`, configure os executáveis:

```dotenv
FFMPEG_BIN=C:\caminho\para\ffmpeg.exe
FFPROBE_BIN=C:\caminho\para\ffprobe.exe
```

Os principais valores opcionais já possuem padrões adequados:

```dotenv
STT_MODEL=base
LLM_MODEL=deepseek-v4-flash
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=alloy
AUDIO_INPUT_MAX_BYTES=10485760
```

O backend não carrega `.env.local` automaticamente. Importe o arquivo para o
processo atual do PowerShell antes de iniciar o servidor:

```powershell
Get-Content .env.local | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#')) {
        $name, $value = $line -split '=', 2
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
    }
}
```

Não versione `.env`, `.env.local` nem chaves reais. Esses arquivos já estão no
`.gitignore`.

### 4.2 Iniciar e verificar o backend

Ainda dentro de `backend/` e com o ambiente virtual ativado:

```powershell
python main.py
```

O servidor deve escutar em `0.0.0.0:8000`. Na primeira execução, o Whisper
pode baixar o modelo `base` e demorar mais para ficar pronto.

Em outro PowerShell:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Resposta esperada:

```text
status audio_ready stream_active
------ ----------- -------------
ok           False         False
```

Se o celular e a ESP32 não conseguirem acessar o backend, libere a porta TCP
8000 no Firewall do Windows para redes privadas.

## 5. Descobrir os endereços IP corretos

No computador que executa o backend:

```powershell
ipconfig
```

Use o endereço **IPv4** do adaptador conectado à mesma rede do ESP32, por
exemplo `192.168.1.13`. Não use `127.0.0.1`, pois esse endereço só funciona no
próprio computador. VPNs e adaptadores virtuais podem mostrar outros IPv4;
prefira o adaptador Wi-Fi/Ethernet realmente conectado à rede local.

O IP da ESP32 aparece no monitor serial:

```text
Wi-Fi conectado, IP=192.168.1.42
web_server.started port=80
```

Neste exemplo:

- backend: `http://192.168.1.13:8000`;
- página do celular: `http://192.168.1.42/`.

Os endereços podem mudar quando os dispositivos reconectam. Para uma
instalação permanente, configure uma reserva DHCP no roteador.

## 6. Configuração e gravação do firmware

Abra um terminal com o ambiente do ESP-IDF 5.5.4 ativado e, na raiz do
repositório, execute:

```powershell
idf.py set-target esp32
idf.py menuconfig
```

No menu `HTTP audio player`, configure:

| Campo | Valor |
|---|---|
| Wi-Fi SSID | nome exato da rede 2,4 GHz |
| Wi-Fi password | senha da rede |
| HTTP PCM stream URL | `http://IP_DO_BACKEND:8000/audio/stream` |
| Backend audio input URL | `http://IP_DO_BACKEND:8000/audio/input` |
| Backend device token | mesmo valor de `AUDIO_INPUT_DEVICE_TOKEN` |
| Maximum phone upload size | `10485760` por padrão |
| Phone web server port | `80` |
| PCM sample rate | `16000` |
| Output volume | começar entre `30` e `55` |
| Audio buffer capacity | `2000` ms |
| Prebuffer before playback | `250` ms |

As duas URLs apontam para o mesmo computador e normalmente usam o mesmo IP.
Uma é usada para enviar a gravação e a outra para receber a resposta PCM.

Compile, grave e abra o monitor serial, substituindo `COMx` pela porta real:

```powershell
idf.py build
idf.py -p COMx flash monitor
```

Para descobrir a porta no Windows:

```powershell
Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Name
```

## 7. Teste ponta a ponta pelo celular

1. Inicie o backend e aguarde o carregamento do Whisper.
2. Ligue a ESP32 e confirme no monitor serial que ela recebeu um IP.
3. Conecte o celular à mesma rede Wi-Fi 2,4 GHz.
4. Abra `http://IP_DA_ESP32/` no navegador do celular.
5. Escolha ou grave um áudio e toque em **Enviar pela ESP32**.
6. Confirme que a página recebeu `HTTP 202` com um `job_id`.
7. Acompanhe o backend processar `converting`, `stt`, `llm`, `tts` e `queued`.
8. Aguarde a ESP32 consumir `/audio/stream` e reproduzir a resposta.

Um upload aceito gera mensagens semelhantes no monitor serial:

```text
phone_upload.accepted ...
proxy.backend_connected ...
proxy.backend_response ... status=202
proxy.completed ...
phone_upload.completed ...
```

Durante a reprodução:

```text
stream conectado: http://IP_DO_BACKEND:8000/audio/stream
playback iniciado com ... ms no buffer
fim do stream HTTP
```

## 8. Contratos HTTP

| Endpoint | Método | Uso |
|---|---|---|
| `/` na ESP32 | `GET` | Página de seleção/gravação do celular |
| `/api/audio/input` na ESP32 | `POST` | Recebe o arquivo e faz proxy progressivo |
| `/audio/input` no backend | `POST` | Recebe o upload autenticado e responde `202` |
| `/audio/input/{job_id}` | `GET` | Consulta o estado do processamento |
| `/audio/stream` | `GET` | Long-poll do PCM para a ESP32 |
| `/health` | `GET` | Saúde e estado da fila |
| `/queue` | `POST` | Compatibilidade e diagnóstico com PCM/WAV |
| `/transcribe` | `POST` | Diagnóstico do STT; não é o fluxo principal |

O áudio entregue em `/audio/stream` possui contrato fixo:

- PCM cru, sem cabeçalho WAV;
- amostras `s16le`;
- mono;
- 16.000 Hz;
- `Content-Type: application/octet-stream`.

## 9. Arquitetura do firmware

O firmware usa ESP-IDF e FreeRTOS, sem ESP-ADF:

- o servidor HTTP entrega a página do celular e recebe
  `POST /api/audio/input`;
- o proxy encaminha o upload em blocos de tamanho fixo, sem manter o arquivo
  inteiro na RAM;
- `http_task`, prioridade 5, executa o long-poll de `/audio/stream`, converte
  PCM16 para DAC8 e alimenta o `StreamBuffer`;
- `playback_task`, prioridade 6, consome o buffer e escreve no DAC;
- o prebuffer reduz cortes causados por variações curtas da rede;
- quando o buffer enche, o bloqueio da leitura propaga backpressure pelo TCP.

## 10. Ligação da saída de áudio

```text
ESP32 GPIO25 (DAC1) -- capacitor eletrolítico 10 µF -- PAM8403 L-IN
ESP32 GND ------------------------------------------ PAM8403 GND
fonte 5 V adequada -------------------------------- PAM8403 VCC
alto-falante 8 Ω / 0,5 W --------------------------- PAM8403 L+ e L-
```

Cuidados:

- o positivo do capacitor eletrolítico fica do lado do ESP32;
- nunca conecte `L-` ou `R-` do PAM8403 ao GND; a saída é BTL;
- mantenha GND comum entre ESP32 e PAM8403;
- use alimentação adequada para o PAM8403;
- comece com volume baixo antes de aumentar o ganho.

## 11. Testes

Com os requirements instalados, a suíte rápida não usa credenciais reais:

```powershell
cd backend
python -m pytest tests -q -m "not stt and not provider"
```

O resultado validado nesta revisão foi `69 passed, 2 deselected`.

O smoke test real do Whisper é separado:

```powershell
$env:RUN_REAL_STT='1'
python -m pytest tests\test_stt_real.py -q -m stt
```

O smoke test da DeepSeek faz uma chamada real e potencialmente cobrada:

```powershell
$env:RUN_REAL_DEEPSEEK='1'
python -m pytest tests\test_deepseek_real.py -q -m provider
```

## 12. Troubleshooting

| Sintoma | Verificação |
|---|---|
| ESP32 repete `Wi-Fi desconectado` | Confirme rede 2,4 GHz, SSID, senha e intensidade do sinal |
| Celular não abre a página | Use o IP da ESP32 mostrado no monitor serial e confirme a mesma rede |
| ESP32 não alcança o backend | Confira o IPv4 do computador, porta 8000, firewall e VPN |
| Upload retorna `503` | Defina `AUDIO_INPUT_DEVICE_TOKEN` no processo do backend |
| Upload retorna `401` | Token do backend e do `menuconfig` são diferentes |
| Upload retorna `202`, mas o job falha no LLM | Confira `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL` e `LLM_MODEL` |
| Job falha no TTS | Confira `OPENAI_API_KEY`, `OPENAI_BASE_URL` e `TTS_MODEL` |
| Job falha em `converting` | Verifique `ffmpeg`, `ffprobe` e o tipo de áudio enviado |
| Firmware registra `HTTP 204` | Comportamento normal quando ainda não existe áudio na fila |
| Áudio apresenta cortes | Verifique sinal Wi-Fi e aumente buffer/prebuffer com moderação |
| Áudio distorce | Reduza `Output volume` e confira alimentação/ligação do PAM8403 |

Para consultar um job retornado pelo upload:

```powershell
Invoke-RestMethod http://IP_DO_BACKEND:8000/audio/input/ID_DO_JOB
```

## 13. Estrutura principal

```text
backend/
├── main.py                         # entrypoint Uvicorn
├── app.py                          # fábrica FastAPI e montagem do pipeline
├── config.py                       # configuração por variáveis de ambiente
├── routes/audio.py                 # fila, stream, health e diagnóstico STT
├── routes/audio_input.py           # upload e consulta de jobs
├── services/audio_upload.py        # recepção progressiva em disco
├── services/audio_pipeline.py      # conversão -> STT -> LLM -> TTS -> fila
├── services/llm_service.py         # DeepSeek Chat Completions
├── services/tts_service.py         # OpenAI Speech API
├── services/stt/                   # Whisper
└── tests/                          # unidades, integração e smoke tests

main/
├── http_audio_player.c             # Wi-Fi, stream PCM, buffer e DAC
├── web_audio_server.c              # página e upload do celular
├── audio_upload_proxy.c            # proxy ESP32 -> backend
├── web_page.h                      # interface web embarcada
└── Kconfig.projbuild               # opções do menuconfig
```

## 14. Limitações e próximos passos

- o ESP32 clássico trabalha apenas em Wi-Fi 2,4 GHz;
- o DAC interno tem 8 bits, com qualidade inferior a um DAC I2S externo;
- a captura ainda depende do celular;
- Whisper em CPU pode adicionar latência;
- LLM e TTS dependem de APIs externas;
- a interface destinada a usuários finais deve informar claramente que a voz
  reproduzida é gerada por IA;
- o tráfego local atual usa HTTP; uma implantação fora de uma rede confiável
  deve adicionar HTTPS, autenticação de usuários e proteção de segredos.

Extensões naturais incluem captura nativa pelo microfone, DAC I2S externo,
atualização OTA, contexto de conversa, telemetria e endurecimento de segurança.

## 15. Referências técnicas

- [ESP-IDF 5.5](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32/):
  Wi-Fi, servidor/cliente HTTP, FreeRTOS e DAC contínuo.
- [OpenAI Whisper](https://github.com/openai/whisper): transcrição automática
  de fala.
- [DeepSeek API](https://api-docs.deepseek.com/): geração da resposta textual
  com `deepseek-v4-flash`.
- [OpenAI Text to speech](https://developers.openai.com/api/docs/guides/text-to-speech):
  síntese com `gpt-4o-mini-tts` pela Speech API.
