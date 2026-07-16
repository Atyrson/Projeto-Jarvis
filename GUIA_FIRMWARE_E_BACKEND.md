# Guia simples: firmware de áudio HTTP da ESP32

Este documento explica o firmware atual sem exigir conhecimento interno do
ESP-IDF. Ele também define exatamente o que o backend precisa enviar para que a
ESP32 reproduza a resposta da IA no alto-falante.

## 1. O que o firmware atual faz

O firmware implementa esta parte da aplicação:

```text
backend/IA
    |
    | resposta HTTP com áudio PCM em pequenos blocos
    v
ESP32 -> buffer de áudio -> DAC GPIO25 -> PAM8403 -> alto-falante
```

A ESP32:

1. conecta-se ao Wi-Fi;
2. faz uma requisição HTTP `GET` para o backend;
3. recebe o áudio aos poucos;
4. converte o áudio PCM de 16 bits para o DAC interno de 8 bits;
5. guarda temporariamente as amostras em um buffer;
6. toca o áudio pelo GPIO25 enquanto continua recebendo os próximos blocos;
7. reconecta automaticamente quando a resposta termina ou a conexão falha.

> **Importante:** o firmware atual recebe e reproduz áudio. A captura do
> microfone e o envio da voz para o backend ainda serão implementados em outra
> etapa.

## 2. Quem inicia a conexão HTTP?

A **ESP32 inicia a conexão**.

Ela faz algo equivalente a:

```http
GET /audio/stream HTTP/1.1
Host: 192.168.1.100:8000
Accept: application/octet-stream
X-Audio-Format: pcm_s16le
X-Audio-Sample-Rate: 16000
X-Audio-Channels: 1
```

O backend recebe esse `GET`, responde imediatamente com `200 OK` e mantém a
resposta aberta enquanto envia os blocos de áudio.

Portanto, o backend não precisa descobrir o IP da ESP32 nem abrir uma conexão
contra ela. Ele apenas disponibiliza um endpoint HTTP que a ESP32 consulta.

## 3. Formato de áudio esperado

O corpo da resposta HTTP deve conter somente áudio com este formato:

| Parâmetro | Valor |
|---|---|
| Formato | PCM cru, sem cabeçalho WAV |
| Tipo da amostra | inteiro com sinal |
| Resolução | 16 bits |
| Ordem dos bytes | little-endian |
| Canais | 1, mono |
| Taxa de amostragem | 16.000 Hz |
| Nome comum | `PCM s16le mono 16 kHz` |
| Content-Type | `application/octet-stream` |

Cada segundo de áudio ocupa:

```text
16.000 amostras × 2 bytes = 32.000 bytes por segundo
```

Esse volume de dados é pequeno para uma rede Wi-Fi.

### O que não pode ser enviado diretamente

O endpoint não deve retornar:

- um arquivo WAV completo;
- MP3;
- AAC;
- Opus;
- texto em Base64;
- JSON contendo áudio;
- áudio estéreo;
- amostras `float`.

Um arquivo WAV normalmente começa com um cabeçalho. Se esse cabeçalho for
enviado, a ESP32 tentará reproduzi-lo como se fosse áudio e produzirá ruído no
início.

## 4. Como converter o áudio da IA

Se o mecanismo de TTS gerar um arquivo WAV ou MP3, o backend deve convertê-lo
para PCM cru antes de transmitir.

Exemplo usando FFmpeg:

```bash
ffmpeg -i resposta.wav -f s16le -acodec pcm_s16le -ac 1 -ar 16000 resposta.pcm
```

Significado das opções:

- `-f s16le`: saída PCM de 16 bits little-endian;
- `-ac 1`: converte para mono;
- `-ar 16000`: converte para 16 kHz;
- `resposta.pcm`: arquivo sem cabeçalho, pronto para o firmware.

Não é obrigatório criar um arquivo intermediário. O backend pode fazer essa
conversão em memória e transmitir os bytes conforme o TTS os produz.

## 5. Como dividir a transmissão

O backend deve enviar o áudio em blocos pequenos. Os blocos não precisam ter
sempre o mesmo tamanho.

Valores recomendados:

| Duração representada | Tamanho em PCM s16le/16 kHz |
|---:|---:|
| 20 ms | 640 bytes |
| 40 ms | 1.280 bytes |
| 50 ms | 1.600 bytes |
| 100 ms | 3.200 bytes |

Uma escolha simples é usar blocos de **1.280 bytes**, equivalentes a 40 ms de
voz.

O backend pode responder de duas maneiras:

1. `Transfer-Encoding: chunked`, recomendado quando o TTS ainda está gerando o
   áudio e o tamanho final não é conhecido;
2. `Content-Length`, quando o áudio completo já está pronto e seu tamanho é
   conhecido.

O firmware aceita os dois casos. O tamanho de um chunk HTTP não precisa ser
igual ao tamanho usado internamente pelo DAC.

## 6. Como o buffer evita cortes

Rede e reprodução não funcionam em uma velocidade perfeitamente constante.
Por isso, o firmware usa duas tarefas separadas:

```text
tarefa HTTP                         tarefa de reprodução
    |                                      |
    | recebe e converte PCM16 -> DAC8      | retira amostras
    v                                      v
             [ buffer compartilhado ] -> DAC -> GPIO25
```

Configuração padrão:

- capacidade do buffer: aproximadamente 2 segundos;
- quantidade mínima antes de começar a tocar: 250 ms;
- leitura HTTP temporária: até 2.048 bytes;
- escrita no DAC: até 1.024 amostras por vez.

### Quando o buffer enche

A tarefa HTTP para de retirar dados do socket até a reprodução liberar espaço.
O TCP percebe isso e reduz automaticamente o envio. Esse mecanismo é chamado de
**backpressure**.

Assim, não é necessário guardar toda a resposta na RAM da ESP32 e nenhum bloco
é descartado simplesmente porque o buffer está cheio.

O backend deve respeitar o fluxo normal do socket. Em frameworks assíncronos,
isso significa aguardar cada operação de escrita ou `yield`, sem disparar todas
as escritas em paralelo.

### Quando o buffer esvazia

Se a rede atrasar e não houver amostras disponíveis:

1. o firmware registra um `underrun` no monitor serial;
2. envia silêncio ao DAC;
3. espera o buffer recuperar o prebuffer;
4. volta a tocar.

Isso evita continuar a reprodução com dados inexistentes ou corrompidos.

## 7. Conversão para o DAC da ESP32

O backend envia PCM de 16 bits porque esse é um formato comum e adequado para
voz e para modelos de IA.

O DAC interno do ESP32 clássico possui 8 bits. O firmware faz a conversão:

```text
PCM16 com sinal: -32768 ... 32767
             |
             | aplica o volume configurado
             v
DAC8 sem sinal: 0 ... 255, com silêncio próximo de 128
```

A taxa continua sendo 16 kHz. Resolução de 8 bits e taxa de 16 kHz são
características diferentes.

O sinal analógico sai pelo **GPIO25 (DAC1)** e segue para o PAM8403.

## 8. Resposta HTTP esperada

Exemplo simplificado:

```http
HTTP/1.1 200 OK
Content-Type: application/octet-stream
Transfer-Encoding: chunked

<bytes PCM s16le mono 16 kHz>
<mais bytes PCM>
<mais bytes PCM>
```

Regras importantes:

- responder com status `200` quando houver um stream válido;
- enviar os cabeçalhos antes de começar um processamento demorado;
- não aplicar compactação HTTP como gzip ao corpo;
- não misturar mensagens de texto ou JSON no corpo;
- encerrar corretamente a resposta ao final do áudio.

Depois que a resposta termina, a ESP32 espera aproximadamente 1 segundo e faz
um novo `GET`. Se o endpoint sempre devolver o mesmo arquivo, a ESP32 tocará o
mesmo áudio repetidamente.

O backend pode manter a resposta aberta esperando a próxima resposta da IA ou
responder `204` enquanto não houver áudio. No caso de `204`, o firmware apenas
registra o status e tenta novamente depois de aproximadamente 1 segundo.

## 9. Exemplo de backend com FastAPI

Este exemplo transmite um arquivo `resposta.pcm` já convertido:

```python
import asyncio

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()


async def gerar_chunks_pcm():
    tamanho_chunk = 1280  # 40 ms em PCM s16le mono/16 kHz

    with open("resposta.pcm", "rb") as audio:
        while chunk := audio.read(tamanho_chunk):
            yield chunk

            # Cede o controle para o servidor e permite que o transporte
            # aplique backpressure. Não cria uma lista com o áudio inteiro.
            await asyncio.sleep(0)


@app.get("/audio/stream")
async def audio_stream():
    return StreamingResponse(
        gerar_chunks_pcm(),
        media_type="application/octet-stream",
    )
```

Para executar:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Se o computador do backend tiver o IP `192.168.1.100`, a URL configurada na
ESP32 será:

```text
http://192.168.1.100:8000/audio/stream
```

O firewall do computador precisa permitir conexões de entrada na porta 8000.

## 10. Integração com a IA

Na aplicação completa, o backend deverá:

```text
1. receber a voz gravada pela ESP32
2. transcrever a voz
3. executar a ação de IA
4. gerar a resposta falada com TTS
5. converter a saída para PCM s16le mono/16 kHz
6. disponibilizar os bytes em /audio/stream
```

Como microfone e alto-falante não precisam funcionar simultaneamente, a ESP32
poderá operar em estados:

```text
AGUARDANDO
    -> GRAVANDO E ENVIANDO
    -> AGUARDANDO A IA
    -> RECEBENDO E REPRODUZINDO
    -> AGUARDANDO
```

No ESP32 clássico, ADC contínuo e DAC contínuo usam o mesmo periférico interno
I2S0. Por isso, o firmware futuro deverá desalocar o ADC antes de iniciar o DAC
e desalocar o DAC antes de voltar a gravar. Essa alternância é compatível com o
fluxo acima.

## 11. Configuração do firmware

Na raiz do projeto, abra um terminal ESP-IDF e execute:

```powershell
idf.py menuconfig
```

Entre no menu `HTTP audio player` e configure:

| Campo | Valor sugerido |
|---|---|
| Wi-Fi SSID | nome da rede 2,4 GHz |
| Wi-Fi password | senha da rede |
| HTTP PCM stream URL | URL completa do endpoint |
| PCM sample rate | `16000` |
| Output volume | começar entre `30` e `55` |
| Audio buffer capacity | `2000` ms |
| Prebuffer before playback | `250` ms |

Compile e grave:

```powershell
idf.py build
idf.py -p COM7 flash monitor
```

Se a porta mudar, substitua `COM7` pela porta exibida no VS Code ou no
Gerenciador de Dispositivos.

## 12. Ligações do alto-falante

```text
ESP32 GPIO25 -- capacitor de 10 uF -- PAM8403 L-IN
ESP32 GND -------------------------- PAM8403 GND
fonte 5 V -------------------------- PAM8403 VCC
alto-falante ----------------------- PAM8403 L+ e L-
```

Cuidados:

- o positivo do capacitor eletrolítico fica do lado do ESP32;
- nunca ligue `L-` ou `R-` do PAM8403 ao GND;
- use GND comum entre ESP32 e PAM8403;
- comece com volume baixo;
- alimente o PAM8403 com uma fonte de 5 V adequada, evitando puxar toda a
  corrente do regulador da placa ESP32.

## 13. Mensagens úteis do monitor serial

| Mensagem | Significado |
|---|---|
| `Wi-Fi conectado, IP=...` | conexão com a rede concluída |
| `stream conectado` | backend respondeu `200` |
| `playback iniciado` | prebuffer atingido e reprodução iniciada |
| `buffer vazio (underrun)` | backend/rede entregou áudio mais lentamente que o consumo |
| `backend respondeu HTTP ...` | endpoint retornou um status diferente de `200` |
| `erro de leitura HTTP` | conexão caiu ou ocorreu erro no socket |
| `fim do stream HTTP` | backend terminou corretamente a resposta |

## 14. Checklist do backend

Antes do teste, confirme:

- [ ] endpoint acessível pelo IP da rede local;
- [ ] resposta HTTP `200 OK`;
- [ ] corpo binário, sem JSON e sem Base64;
- [ ] PCM cru `s16le`;
- [ ] mono;
- [ ] 16 kHz;
- [ ] sem cabeçalho WAV;
- [ ] chunks pequenos, por exemplo 1.280 bytes;
- [ ] escrita sequencial respeitando backpressure;
- [ ] firewall liberando a porta do backend.

