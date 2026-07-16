#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "driver/dac_continuous.h"
#include "esp_check.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "web_audio_server.h"

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_MAX_RETRIES 10
#define HTTP_READ_BYTES 2048
#define HTTP_TIMEOUT_MS 35000
#define DAC_WRITE_SAMPLES 1024
#define HTTP_RECONNECT_DELAY_MS 1000
#define STRINGIFY_INNER(value) #value
#define STRINGIFY(value) STRINGIFY_INNER(value)

static const char *TAG = "http_audio";

static EventGroupHandle_t s_wifi_events;
static StreamBufferHandle_t s_audio_buffer;
static dac_continuous_handle_t s_dac;
static volatile bool s_http_receiving;
static int s_wifi_retries;

static size_t audio_buffer_samples(void)
{
    return ((size_t)CONFIG_AUDIO_SAMPLE_RATE * CONFIG_AUDIO_BUFFER_MS) / 1000;
}

static size_t prebuffer_samples(void)
{
    size_t samples = ((size_t)CONFIG_AUDIO_SAMPLE_RATE * CONFIG_AUDIO_PREBUFFER_MS) / 1000;
    size_t capacity = audio_buffer_samples();
    return samples < capacity ? samples : capacity / 2;
}

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT);
        s_http_receiving = false;
        ++s_wifi_retries;
        if (s_wifi_retries > WIFI_MAX_RETRIES) {
            s_wifi_retries = 0;
            ESP_LOGE(TAG, "Wi-Fi ainda indisponivel; continuando as tentativas");
        } else {
            ESP_LOGW(TAG, "Wi-Fi desconectado; tentativa %d/%d", s_wifi_retries, WIFI_MAX_RETRIES);
        }
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = data;
        ESP_LOGI(TAG, "Wi-Fi conectado, IP=" IPSTR, IP2STR(&event->ip_info.ip));
        s_wifi_retries = 0;
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
        esp_err_t web_err = web_audio_server_start();
        if (web_err != ESP_OK) {
            ESP_LOGE(TAG, "falha ao iniciar servidor web: %s", esp_err_to_name(web_err));
        }
    }
}

static esp_err_t wifi_init(void)
{
    s_wifi_events = xEventGroupCreate();
    ESP_RETURN_ON_FALSE(s_wifi_events, ESP_ERR_NO_MEM, TAG, "sem memoria para eventos Wi-Fi");

    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "esp_netif_init");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "event loop");
    ESP_RETURN_ON_FALSE(esp_netif_create_default_wifi_sta(), ESP_ERR_NO_MEM, TAG, "netif Wi-Fi");

    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&init_cfg), TAG, "esp_wifi_init");
    ESP_RETURN_ON_ERROR(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                   wifi_event_handler, NULL), TAG, "handler Wi-Fi");
    ESP_RETURN_ON_ERROR(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                   wifi_event_handler, NULL), TAG, "handler IP");

    wifi_config_t cfg = {0};
    strlcpy((char *)cfg.sta.ssid, CONFIG_AUDIO_WIFI_SSID, sizeof(cfg.sta.ssid));
    strlcpy((char *)cfg.sta.password, CONFIG_AUDIO_WIFI_PASSWORD, sizeof(cfg.sta.password));
    cfg.sta.threshold.authmode = strlen(CONFIG_AUDIO_WIFI_PASSWORD) ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    cfg.sta.pmf_cfg.capable = true;
    cfg.sta.pmf_cfg.required = false;

    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "modo station");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &cfg), TAG, "config Wi-Fi");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "start Wi-Fi");
    return ESP_OK;
}

static esp_err_t dac_init(void)
{
    const dac_continuous_config_t cfg = {
        .chan_mask = DAC_CHANNEL_MASK_CH0,
        .desc_num = 8,
        .buf_size = DAC_WRITE_SAMPLES,
        .freq_hz = CONFIG_AUDIO_SAMPLE_RATE,
        .offset = 0,
        .clk_src = DAC_DIGI_CLK_SRC_APLL,
        .chan_mode = DAC_CHANNEL_MODE_SIMUL,
    };
    ESP_RETURN_ON_ERROR(dac_continuous_new_channels(&cfg, &s_dac), TAG, "criar DAC");
    ESP_RETURN_ON_ERROR(dac_continuous_enable(s_dac), TAG, "habilitar DAC");
    ESP_LOGI(TAG, "DAC em GPIO25, %d Hz, 8 bits", CONFIG_AUDIO_SAMPLE_RATE);
    return ESP_OK;
}

static uint8_t pcm16_to_dac8(int16_t sample)
{
    int32_t scaled = ((int32_t)sample * CONFIG_AUDIO_VOLUME_PERCENT) / 100;
    int32_t value = (scaled >> 8) + 128;
    if (value < 0) {
        value = 0;
    } else if (value > 255) {
        value = 255;
    }
    return (uint8_t)value;
}

static bool enqueue_dac(const uint8_t *data, size_t length)
{
    size_t sent = 0;
    while (sent < length) {
        size_t n = xStreamBufferSend(s_audio_buffer, data + sent, length - sent,
                                     pdMS_TO_TICKS(1000));
        if (n == 0 && !(xEventGroupGetBits(s_wifi_events) & WIFI_CONNECTED_BIT)) {
            return false;
        }
        sent += n;
    }
    return true;
}

static void http_stream_once(void)
{
    esp_http_client_config_t cfg = {
        .url = CONFIG_AUDIO_STREAM_URL,
        /* O backend faz long-poll por ate 30 s antes de responder 204. */
        .timeout_ms = HTTP_TIMEOUT_MS,
        .buffer_size = HTTP_READ_BYTES,
        .user_agent = "esp32-http-audio/1.0",
        .keep_alive_enable = true,
        .disable_auto_redirect = false,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) {
        ESP_LOGE(TAG, "falha ao criar cliente HTTP");
        return;
    }

    esp_http_client_set_header(client, "Accept", "application/octet-stream");
    esp_http_client_set_header(client, "X-Audio-Format", "pcm_s16le");
    esp_http_client_set_header(client, "X-Audio-Sample-Rate", STRINGIFY(CONFIG_AUDIO_SAMPLE_RATE));
    esp_http_client_set_header(client, "X-Audio-Channels", "1");

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "HTTP open: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return;
    }
    (void)esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    if (status != 200) {
        ESP_LOGW(TAG, "backend respondeu HTTP %d", status);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return;
    }

    ESP_LOGI(TAG, "stream conectado: %s%s", CONFIG_AUDIO_STREAM_URL,
             esp_http_client_is_chunked_response(client) ? " (chunked)" : "");
    s_http_receiving = true;

    uint8_t *http_data = malloc(HTTP_READ_BYTES);
    uint8_t *dac_data = malloc((HTTP_READ_BYTES / 2) + 1);
    if (!http_data || !dac_data) {
        ESP_LOGE(TAG, "sem memoria para buffers HTTP");
        free(http_data);
        free(dac_data);
        goto close_client;
    }

    bool have_low_byte = false;
    uint8_t low_byte = 0;
    while (xEventGroupGetBits(s_wifi_events) & WIFI_CONNECTED_BIT) {
        int read = esp_http_client_read(client, (char *)http_data, HTTP_READ_BYTES);
        if (read == -ESP_ERR_HTTP_EAGAIN) {
            continue;
        }
        if (read < 0) {
            ESP_LOGW(TAG, "erro de leitura HTTP");
            break;
        }
        if (read == 0) {
            if (esp_http_client_is_complete_data_received(client)) {
                ESP_LOGI(TAG, "fim do stream HTTP");
            } else {
                ESP_LOGW(TAG, "stream HTTP encerrado antes do fim");
            }
            break;
        }

        size_t out = 0;
        int pos = 0;
        if (have_low_byte) {
            int16_t sample = (int16_t)((uint16_t)low_byte | ((uint16_t)http_data[0] << 8));
            dac_data[out++] = pcm16_to_dac8(sample);
            have_low_byte = false;
            pos = 1;
        }
        while (pos + 1 < read) {
            int16_t sample = (int16_t)((uint16_t)http_data[pos] |
                                       ((uint16_t)http_data[pos + 1] << 8));
            dac_data[out++] = pcm16_to_dac8(sample);
            pos += 2;
        }
        if (pos < read) {
            low_byte = http_data[pos];
            have_low_byte = true;
        }
        if (out && !enqueue_dac(dac_data, out)) {
            break;
        }
    }

    if (have_low_byte) {
        ESP_LOGW(TAG, "byte PCM incompleto descartado no fim da conexao");
    }
    free(http_data);
    free(dac_data);

close_client:
    s_http_receiving = false;
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
}

static void http_task(void *arg)
{
    for (;;) {
        xEventGroupWaitBits(s_wifi_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
        http_stream_once();
        vTaskDelay(pdMS_TO_TICKS(HTTP_RECONNECT_DELAY_MS));
    }
}

static void playback_task(void *arg)
{
    uint8_t *samples = malloc(DAC_WRITE_SAMPLES);
    if (!samples) {
        ESP_LOGE(TAG, "sem memoria para playback");
        vTaskDelete(NULL);
    }

    bool started = false;
    uint32_t underruns = 0;
    for (;;) {
        size_t available = xStreamBufferBytesAvailable(s_audio_buffer);
        if (!started) {
            if (available < prebuffer_samples() && s_http_receiving) {
                memset(samples, 128, DAC_WRITE_SAMPLES);
                size_t silence_loaded = 0;
                ESP_ERROR_CHECK(dac_continuous_write(s_dac, samples, DAC_WRITE_SAMPLES,
                                                     &silence_loaded, -1));
                continue;
            }
            if (available == 0) {
                memset(samples, 128, DAC_WRITE_SAMPLES);
                size_t silence_loaded = 0;
                ESP_ERROR_CHECK(dac_continuous_write(s_dac, samples, DAC_WRITE_SAMPLES,
                                                     &silence_loaded, -1));
                continue;
            }
            ESP_LOGI(TAG, "playback iniciado com %u ms no buffer",
                     (unsigned)((available * 1000) / CONFIG_AUDIO_SAMPLE_RATE));
            started = true;
        }

        size_t received = xStreamBufferReceive(s_audio_buffer, samples,
                                               DAC_WRITE_SAMPLES, pdMS_TO_TICKS(100));
        if (received == 0) {
            ++underruns;
            ESP_LOGW(TAG, "buffer vazio (underrun %lu); aguardando prebuffer", (unsigned long)underruns);
            started = false;
            continue;
        }

        size_t loaded = 0;
        esp_err_t err = dac_continuous_write(s_dac, samples, received, &loaded, -1);
        if (err != ESP_OK || loaded != received) {
            ESP_LOGE(TAG, "DAC write: %s (%u/%u)", esp_err_to_name(err),
                     (unsigned)loaded, (unsigned)received);
        }
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "HTTP PCM: s16le, mono, %d Hz; buffer=%d ms, prebuffer=%d ms",
             CONFIG_AUDIO_SAMPLE_RATE, CONFIG_AUDIO_BUFFER_MS, CONFIG_AUDIO_PREBUFFER_MS);

    esp_err_t nvs_err = nvs_flash_init();
    if (nvs_err == ESP_ERR_NVS_NO_FREE_PAGES || nvs_err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_err);
    ESP_ERROR_CHECK(dac_init());

    s_audio_buffer = xStreamBufferCreate(audio_buffer_samples(), 1);
    ESP_ERROR_CHECK(s_audio_buffer ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(wifi_init());

    xTaskCreate(playback_task, "audio_playback", 4096, NULL, 6, NULL);
    xTaskCreate(http_task, "http_stream", 6144, NULL, 5, NULL);
}
