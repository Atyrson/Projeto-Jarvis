#pragma once

#include "esp_err.h"
#include "esp_http_server.h"

esp_err_t audio_upload_proxy_forward(httpd_req_t *req);
