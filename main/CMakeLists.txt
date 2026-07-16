idf_component_register(
    SRCS "http_audio_player.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_driver_dac esp_event esp_http_client esp_netif esp_wifi nvs_flash
)
