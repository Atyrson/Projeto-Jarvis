#include <math.h>
#include <stdint.h>
#include <stdlib.h>

#include "driver/dac_continuous.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define SAMPLE_RATE 16000
#define BLOCK_SAMPLES 256
#define VOLUME 42
#define PI_F 3.14159265358979323846f

typedef struct {
    uint16_t frequency_hz;
    uint16_t duration_ms;
} note_t;

static const char *TAG = "star_wars_test";

/* Trecho curto e monofonico para validar toda a cadeia de audio. */
static const note_t melody[] = {
    {440, 500}, {440, 500}, {440, 500}, {349, 350}, {523, 150},
    {440, 500}, {349, 350}, {523, 150}, {440, 650}, {0, 180},
    {659, 500}, {659, 500}, {659, 500}, {698, 350}, {523, 150},
    {415, 500}, {349, 350}, {523, 150}, {440, 650}, {0, 600},
};

static void play_note(dac_continuous_handle_t dac, uint8_t *buffer, const note_t *note)
{
    uint32_t total = ((uint32_t)SAMPLE_RATE * note->duration_ms) / 1000;
    uint32_t produced = 0;
    float phase = 0.0f;
    float phase_step = note->frequency_hz ? (2.0f * PI_F * note->frequency_hz / SAMPLE_RATE) : 0.0f;

    while (produced < total) {
        size_t count = total - produced;
        if (count > BLOCK_SAMPLES) {
            count = BLOCK_SAMPLES;
        }
        for (size_t i = 0; i < count; ++i) {
            uint32_t position = produced + i;
            uint32_t edge = SAMPLE_RATE / 200;
            float envelope = 1.0f;
            if (position < edge) {
                envelope = (float)position / edge;
            } else if (total - position < edge) {
                envelope = (float)(total - position) / edge;
            }
            buffer[i] = note->frequency_hz
                            ? (uint8_t)(128.0f + sinf(phase) * VOLUME * envelope)
                            : 128;
            phase += phase_step;
            if (phase >= 2.0f * PI_F) {
                phase -= 2.0f * PI_F;
            }
        }
        size_t loaded = 0;
        ESP_ERROR_CHECK(dac_continuous_write(dac, buffer, count, &loaded, -1));
        produced += loaded;
    }
}

void app_main(void)
{
    dac_continuous_handle_t dac = NULL;
    const dac_continuous_config_t cfg = {
        .chan_mask = DAC_CHANNEL_MASK_CH0,
        .desc_num = 8,
        .buf_size = BLOCK_SAMPLES,
        .freq_hz = SAMPLE_RATE,
        .offset = 0,
        .clk_src = DAC_DIGI_CLK_SRC_APLL,
        .chan_mode = DAC_CHANNEL_MODE_SIMUL,
    };
    ESP_ERROR_CHECK(dac_continuous_new_channels(&cfg, &dac));
    ESP_ERROR_CHECK(dac_continuous_enable(dac));

    uint8_t *buffer = malloc(BLOCK_SAMPLES);
    ESP_ERROR_CHECK(buffer ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_LOGI(TAG, "Teste iniciado: audio analogico no GPIO25 (DAC1)");

    for (;;) {
        for (size_t i = 0; i < sizeof(melody) / sizeof(melody[0]); ++i) {
            play_note(dac, buffer, &melody[i]);
        }
        ESP_LOGI(TAG, "Melodia concluida; repetindo em 2 segundos");
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}
