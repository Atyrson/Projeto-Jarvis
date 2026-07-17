#include "audio_upload_proxy.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"

#define HEADER_CONTENT_TYPE_BYTES 64
#define HEADER_FILENAME_BYTES 128
#define HEADER_ID_BYTES 40
#define PROGRESS_BYTES (256 * 1024)

static const char *TAG = "audio_proxy";
static uint32_t s_request_sequence;
static portMUX_TYPE s_request_lock = portMUX_INITIALIZER_UNLOCKED;

static esp_err_t send_json_error(httpd_req_t *req, const char *status,
                                 const char *error)
{
    char body[160];
    int written = snprintf(body, sizeof(body), "{\"error\":\"%s\"}", error);
    httpd_resp_set_status(req, status);
    httpd_resp_set_type(req, "application/json");
    return httpd_resp_send(req, body, written);
}

static const char *status_reason(int status)
{
    switch (status) {
    case 200: return "OK";
    case 202: return "Accepted";
    case 400: return "Bad Request";
    case 401: return "Unauthorized";
    case 409: return "Conflict";
    case 411: return "Length Required";
    case 413: return "Content Too Large";
    case 415: return "Unsupported Media Type";
    case 500: return "Internal Server Error";
    case 503: return "Service Unavailable";
    default: return "Backend Response";
    }
}

static uint32_t next_request_sequence(void)
{
    portENTER_CRITICAL(&s_request_lock);
    uint32_t sequence = ++s_request_sequence;
    portEXIT_CRITICAL(&s_request_lock);
    return sequence;
}

static void sanitize_header(char *value)
{
    for (size_t i = 0; value[i] != '\0'; ++i) {
        unsigned char current = (unsigned char)value[i];
        if (current < 32 || current > 126 || current == '\r' || current == '\n') {
            value[i] = '_';
        }
    }
}

static esp_err_t write_all(esp_http_client_handle_t client, const char *data,
                           size_t length)
{
    size_t written = 0;
    while (written < length) {
        int result = esp_http_client_write(client, data + written, length - written);
        if (result <= 0) {
            return ESP_FAIL;
        }
        written += (size_t)result;
    }
    return ESP_OK;
}

esp_err_t audio_upload_proxy_forward(httpd_req_t *req)
{
    char content_type[HEADER_CONTENT_TYPE_BYTES] = "application/octet-stream";
    char filename[HEADER_FILENAME_BYTES] = "audio";
    (void)httpd_req_get_hdr_value_str(req, "Content-Type", content_type,
                                      sizeof(content_type));
    (void)httpd_req_get_hdr_value_str(req, "X-Audio-Filename", filename,
                                      sizeof(filename));
    sanitize_header(content_type);
    sanitize_header(filename);

    uint8_t mac[6];
    if (esp_read_mac(mac, ESP_MAC_WIFI_STA) != ESP_OK) {
        memset(mac, 0, sizeof(mac));
    }
    char device_id[HEADER_ID_BYTES];
    snprintf(device_id, sizeof(device_id), "esp32-%02x%02x%02x", mac[3], mac[4], mac[5]);
    uint32_t sequence = next_request_sequence();
    char request_id[HEADER_ID_BYTES];
    snprintf(request_id, sizeof(request_id), "esp32-%08lu", (unsigned long)sequence);

    ESP_LOGI(TAG, "proxy.backend_connecting request_id=%s bytes_expected=%u heap_free=%lu",
             request_id, (unsigned)req->content_len,
             (unsigned long)esp_get_free_heap_size());
    esp_http_client_config_t config = {
        .url = CONFIG_AUDIO_INPUT_URL,
        .timeout_ms = CONFIG_AUDIO_UPLOAD_TIMEOUT_MS,
        .buffer_size = CONFIG_AUDIO_UPLOAD_BUFFER_SIZE,
        .user_agent = "esp32-audio-upload/1.0",
        .keep_alive_enable = true,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        return send_json_error(req, "502 Bad Gateway", "backend indisponivel");
    }

    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "Content-Type", content_type);
    esp_http_client_set_header(client, "X-Audio-Filename", filename);
    esp_http_client_set_header(client, "X-Request-Id", request_id);
    esp_http_client_set_header(client, "X-Source-Device", "esp32");
    esp_http_client_set_header(client, "X-Device-Id", device_id);
    esp_http_client_set_header(client, "X-Device-Token", CONFIG_AUDIO_DEVICE_TOKEN);

    esp_err_t err = esp_http_client_open(client, req->content_len);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "proxy.failed request_id=%s phase=connecting error=%s",
                 request_id, esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return send_json_error(req, "502 Bad Gateway", "backend indisponivel");
    }
    ESP_LOGI(TAG, "proxy.backend_connected request_id=%s", request_id);

    char *buffer = malloc(CONFIG_AUDIO_UPLOAD_BUFFER_SIZE);
    if (!buffer) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return send_json_error(req, "500 Internal Server Error", "memoria insuficiente");
    }

    size_t remaining = req->content_len;
    size_t forwarded = 0;
    size_t next_progress = PROGRESS_BYTES;
    int64_t started_us = esp_timer_get_time();
    int64_t last_progress_us = started_us;
    while (remaining > 0) {
        size_t wanted = remaining < CONFIG_AUDIO_UPLOAD_BUFFER_SIZE
                            ? remaining
                            : CONFIG_AUDIO_UPLOAD_BUFFER_SIZE;
        int received = httpd_req_recv(req, buffer, wanted);
        if (received <= 0) {
            ESP_LOGW(TAG, "proxy.aborted request_id=%s bytes_forwarded=%u",
                     request_id, (unsigned)forwarded);
            free(buffer);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            return ESP_FAIL;
        }
        if (write_all(client, buffer, (size_t)received) != ESP_OK) {
            ESP_LOGE(TAG, "proxy.failed request_id=%s phase=forwarding bytes_forwarded=%u",
                     request_id, (unsigned)forwarded);
            free(buffer);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            return send_json_error(req, "502 Bad Gateway", "falha ao enviar ao backend");
        }
        forwarded += (size_t)received;
        remaining -= (size_t)received;
        int64_t now_us = esp_timer_get_time();
        if (forwarded >= next_progress || now_us - last_progress_us >= 1000000) {
            ESP_LOGI(TAG, "proxy.progress request_id=%s bytes_forwarded=%u heap_free=%lu",
                     request_id, (unsigned)forwarded,
                     (unsigned long)esp_get_free_heap_size());
            ESP_LOGI(TAG, "phone_upload.progress request_id=%s bytes_received=%u",
                     request_id, (unsigned)forwarded);
            next_progress = forwarded + PROGRESS_BYTES;
            last_progress_us = now_us;
        }
    }

    int64_t response_length = esp_http_client_fetch_headers(client);
    if (response_length < 0) {
        ESP_LOGE(TAG, "proxy.failed request_id=%s phase=backend_response", request_id);
        free(buffer);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return send_json_error(req, "502 Bad Gateway", "resposta invalida do backend");
    }
    int backend_status = esp_http_client_get_status_code(client);
    ESP_LOGI(TAG, "proxy.backend_response request_id=%s status=%d", request_id,
             backend_status);

    char response_status[48];
    snprintf(response_status, sizeof(response_status), "%d %s", backend_status,
             status_reason(backend_status));
    httpd_resp_set_status(req, response_status);
    char *backend_content_type = NULL;
    if (esp_http_client_get_header(client, "Content-Type", &backend_content_type) == ESP_OK &&
        backend_content_type) {
        httpd_resp_set_type(req, backend_content_type);
    } else {
        httpd_resp_set_type(req, "application/json");
    }

    while (true) {
        int read = esp_http_client_read(client, buffer, CONFIG_AUDIO_UPLOAD_BUFFER_SIZE);
        if (read == -ESP_ERR_HTTP_EAGAIN) {
            continue;
        }
        if (read < 0) {
            err = ESP_FAIL;
            break;
        }
        if (read == 0) {
            err = ESP_OK;
            break;
        }
        if (httpd_resp_send_chunk(req, buffer, read) != ESP_OK) {
            err = ESP_FAIL;
            break;
        }
    }
    if (err == ESP_OK) {
        err = httpd_resp_send_chunk(req, NULL, 0);
    }
    ESP_LOGI(TAG,
             "proxy.completed request_id=%s status=%d bytes_forwarded=%u elapsed_ms=%lld heap_free=%lu",
             request_id, backend_status, (unsigned)forwarded,
             (long long)((esp_timer_get_time() - started_us) / 1000),
             (unsigned long)esp_get_free_heap_size());
    free(buffer);
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return err;
}
