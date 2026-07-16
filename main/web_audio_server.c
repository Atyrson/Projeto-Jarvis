#include "web_audio_server.h"

#include <stdbool.h>
#include <string.h>

#include "audio_upload_proxy.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "web_page.h"

static const char *TAG = "audio_web";
static httpd_handle_t s_server;
static SemaphoreHandle_t s_upload_mutex;

static esp_err_t page_handler(httpd_req_t *req)
{
    ESP_LOGI(TAG, "web_page.served");
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, AUDIO_WEB_PAGE, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t upload_handler(httpd_req_t *req)
{
    if (req->content_len <= 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "corpo vazio");
        return ESP_FAIL;
    }
    if (req->content_len > CONFIG_AUDIO_UPLOAD_MAX_BYTES) {
        ESP_LOGW(TAG, "phone_upload.rejected reason=too_large bytes_expected=%u",
                 (unsigned)req->content_len);
        httpd_resp_set_status(req, "413 Content Too Large");
        httpd_resp_set_type(req, "application/json");
        return httpd_resp_sendstr(req, "{\"error\":\"arquivo acima do limite\"}");
    }

    char content_type[64] = {0};
    if (httpd_req_get_hdr_value_str(req, "Content-Type", content_type,
                                    sizeof(content_type)) != ESP_OK ||
        strncmp(content_type, "audio/", 6) != 0) {
        ESP_LOGW(TAG, "phone_upload.rejected reason=unsupported_media_type");
        httpd_resp_set_status(req, "415 Unsupported Media Type");
        httpd_resp_set_type(req, "application/json");
        return httpd_resp_sendstr(req, "{\"error\":\"tipo de audio nao suportado\"}");
    }
    if (xSemaphoreTake(s_upload_mutex, 0) != pdTRUE) {
        ESP_LOGW(TAG, "phone_upload.rejected reason=busy");
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "application/json");
        return httpd_resp_sendstr(req, "{\"error\":\"upload em andamento\"}");
    }

    ESP_LOGI(TAG, "phone_upload.accepted bytes_expected=%u heap_free=%lu",
             (unsigned)req->content_len, (unsigned long)esp_get_free_heap_size());
    esp_err_t result = audio_upload_proxy_forward(req);
    xSemaphoreGive(s_upload_mutex);
    if (result == ESP_OK) {
        ESP_LOGI(TAG, "phone_upload.completed bytes_received=%u heap_free=%lu",
                 (unsigned)req->content_len, (unsigned long)esp_get_free_heap_size());
    } else {
        ESP_LOGW(TAG, "phone_upload.rejected reason=proxy_failed");
    }
    return result;
}

esp_err_t web_audio_server_start(void)
{
    if (s_server) {
        return ESP_OK;
    }
    if (!s_upload_mutex) {
        s_upload_mutex = xSemaphoreCreateMutex();
        if (!s_upload_mutex) {
            return ESP_ERR_NO_MEM;
        }
    }
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = CONFIG_AUDIO_WEB_SERVER_PORT;
    config.ctrl_port = CONFIG_AUDIO_WEB_SERVER_PORT + 1;
    config.stack_size = 6144;
    config.max_uri_handlers = 4;
    esp_err_t err = httpd_start(&s_server, &config);
    if (err != ESP_OK) {
        s_server = NULL;
        ESP_LOGE(TAG, "web_server.failed error=%s", esp_err_to_name(err));
        return err;
    }
    const httpd_uri_t page = {
        .uri = "/",
        .method = HTTP_GET,
        .handler = page_handler,
    };
    const httpd_uri_t upload = {
        .uri = "/api/audio/input",
        .method = HTTP_POST,
        .handler = upload_handler,
    };
    ESP_ERROR_CHECK_WITHOUT_ABORT(httpd_register_uri_handler(s_server, &page));
    ESP_ERROR_CHECK_WITHOUT_ABORT(httpd_register_uri_handler(s_server, &upload));
    ESP_LOGI(TAG, "web_server.started port=%d", CONFIG_AUDIO_WEB_SERVER_PORT);
    return ESP_OK;
}
