idf_component_register(
    SRCS "web_audio_server.c" "audio_upload_proxy.c" "http_audio_player.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_driver_dac esp_event esp_http_client esp_http_server esp_netif esp_timer esp_wifi nvs_flash
)
