from pathlib import Path


ROOT = Path(__file__).parents[2]
WEB_PAGE = (ROOT / "main" / "web_page.h").read_text(encoding="utf-8")
WEB_SERVER = (ROOT / "main" / "web_audio_server.c").read_text(encoding="utf-8")
PROXY = (ROOT / "main" / "audio_upload_proxy.c").read_text(encoding="utf-8")
KCONFIG = (ROOT / "main" / "Kconfig.projbuild").read_text(encoding="utf-8")
CMAKE = (ROOT / "main" / "CMakeLists.txt").read_text(encoding="utf-8")
FIRMWARE = (ROOT / "main" / "http_audio_player.c").read_text(encoding="utf-8")


def test_web_page_sends_file_directly_with_progress() -> None:
    assert "capture='user'" in WEB_PAGE
    assert "xhr.upload.onprogress" in WEB_PAGE
    assert "xhr.send(f)" in WEB_PAGE
    assert "arrayBuffer" not in WEB_PAGE
    assert "FileReader" not in WEB_PAGE
    assert "multipart/form-data" not in WEB_PAGE


def test_web_server_limits_size_mime_and_concurrency() -> None:
    assert 'uri = "/api/audio/input"' in WEB_SERVER
    assert "CONFIG_AUDIO_UPLOAD_MAX_BYTES" in WEB_SERVER
    assert 'strncmp(content_type, "audio/", 6)' in WEB_SERVER
    assert "xSemaphoreTake(s_upload_mutex, 0)" in WEB_SERVER
    assert '"409 Conflict"' in WEB_SERVER
    assert '"413 Content Too Large"' in WEB_SERVER
    assert '"415 Unsupported Media Type"' in WEB_SERVER


def test_proxy_uses_fixed_buffer_and_handles_partial_writes() -> None:
    assert "req->content_len" in PROXY
    assert "malloc(CONFIG_AUDIO_UPLOAD_BUFFER_SIZE)" in PROXY
    assert "while (written < length)" in PROXY
    assert "httpd_req_recv(req, buffer, wanted)" in PROXY
    assert "write_all(client, buffer" in PROXY
    assert '"X-Device-Token"' in PROXY
    assert '"X-Request-Id"' in PROXY
    assert '"X-Device-Id"' in PROXY
    assert "CONFIG_AUDIO_DEVICE_TOKEN" not in WEB_PAGE


def test_firmware_configuration_and_components_are_registered() -> None:
    for option in (
        "AUDIO_INPUT_URL",
        "AUDIO_UPLOAD_MAX_BYTES",
        "AUDIO_UPLOAD_BUFFER_SIZE",
        "AUDIO_DEVICE_TOKEN",
        "AUDIO_WEB_SERVER_PORT",
    ):
        assert f"config {option}" in KCONFIG
    assert "default 4096" in KCONFIG
    assert '"web_audio_server.c"' in CMAKE
    assert '"audio_upload_proxy.c"' in CMAKE
    assert "esp_http_server" in CMAKE


def test_wifi_disconnect_log_includes_numeric_and_named_reason() -> None:
    assert "wifi_event_sta_disconnected_t" in FIRMWARE
    assert "event->reason" in FIRMWARE
    assert "wifi_reason_name(reason)" in FIRMWARE
    assert 'reason=%u (%s)' in FIRMWARE
    assert 'return "no_ap_found"' in FIRMWARE
    assert 'return "auth_failed"' in FIRMWARE
    assert 'return "handshake_timeout"' in FIRMWARE
