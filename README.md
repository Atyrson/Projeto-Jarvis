# ESP32 HTTP audio player

Firmware ESP-IDF para um **ESP32 classico** receber audio por HTTP e reproduzir
pelo DAC interno no GPIO25, ligado a um amplificador PAM8403.

Para uma explicacao detalhada e simples do fluxo e do contrato esperado do
backend, consulte [GUIA_FIRMWARE_E_BACKEND.md](GUIA_FIRMWARE_E_BACKEND.md).

## Hardware

O projeto usa o DAC interno do ESP32 original (ESP32-WROOM-32/DevKit V1).
ESP32-C3, S3 e variantes sem DAC interno precisam de um DAC I2S externo.

Ligacao para um canal:

```text
ESP32 GPIO25 (DAC1) -- capacitor 10 uF -- PAM8403 L-IN
ESP32 GND ----------------------------- PAM8403 GND
fonte 5 V adequada -------------------- PAM8403 VCC
alto-falante -------------------------- PAM8403 L+ e L-
```

O positivo do capacitor eletrolitico fica do lado do ESP32. Nao ligue `L-` ou
`R-` do PAM8403 ao GND: a saida do amplificador e em ponte (BTL). Comece com
volume baixo e use uma fonte de 5 V adequada ao amplificador.

## 1. Teste do PAM8403 (melodia)

No terminal ESP-IDF:

```powershell
cd examples\star_wars_test
idf.py set-target esp32
idf.py build
idf.py -p COMx flash monitor
```

Troque `COMx` pela porta da placa. O teste gera a melodia localmente e valida
ESP32, DAC, capacitor, PAM8403 e alto-falante sem Wi-Fi ou backend.

## 2. Player HTTP

Na raiz do projeto:

```powershell
idf.py set-target esp32
idf.py menuconfig
```

Em `HTTP audio player`, informe SSID, senha, URL HTTP, sample rate, volume e
tempos de buffer. Para compilar e gravar:

```powershell
idf.py build
idf.py -p COMx flash monitor
```

## Contrato do backend

O endpoint responde `200 OK`, preferencialmente com
`Content-Type: application/octet-stream` e `Transfer-Encoding: chunked`.
O corpo precisa ser PCM cru, sem cabecalho WAV:

- signed 16-bit little-endian (`s16le`);
- mono;
- 16000 amostras/s por padrao.

O ESP32 envia `X-Audio-Format`, `X-Audio-Sample-Rate` e `X-Audio-Channels`.
Envios de 20 a 100 ms funcionam bem; em 16 kHz mono s16le, correspondem a 640
a 3200 bytes. O tamanho do chunk HTTP nao precisa ser constante.

O firmware converte PCM16 para DAC de 8 bits e guarda cerca de 2 segundos. Ao
encher, ele pausa a leitura do socket; o controle de fluxo TCP aplica
backpressure ao backend, sem descartar chunks. Em falta de dados, registra
`underrun` e espera recompor o prebuffer antes de continuar.

Exemplo conceitual em Python:

```python
async def stream_pcm(response, pcm_chunks):
    response.headers["Content-Type"] = "application/octet-stream"
    for chunk in pcm_chunks:
        await response.write(chunk)  # s16le, mono, 16 kHz
        await asyncio.sleep(0)       # respeita o backpressure
```

Nao envie MP3, WAV, Opus ou JSON neste endpoint. Codecs comprimidos exigem um
decoder adicional e mais RAM/CPU no ESP32.
