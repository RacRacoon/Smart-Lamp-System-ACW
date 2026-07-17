#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"

// Include custom drivers
#include "pzem_driver.h"
#include "rtc_driver.h"
#include "gps_driver.h"

static const char *TAG = "MAIN_APP";

#define RELAY_PIN       47
#define LDR_ADC_CHAN    ADC_CHANNEL_8 // GPIO9

adc_oneshot_unit_handle_t adc1_handle;

// Inisialisasi Relay
void init_relay() {
    gpio_config_t io_conf = {
        .intr_type = GPIO_INTR_DISABLE,
        .mode = GPIO_MODE_OUTPUT,
        .pin_bit_mask = (1ULL << RELAY_PIN),
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .pull_up_en = GPIO_PULLUP_DISABLE
    };
    gpio_config(&io_conf);
    gpio_set_level(RELAY_PIN, 1);
    ESP_LOGI(TAG, "Relay initialized.");
}

// Inisialisasi ADC (LDR)
void init_adc_ldr() {
    adc_oneshot_unit_init_cfg_t init_config1 = { .unit_id = ADC_UNIT_1 };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&init_config1, &adc1_handle));

    adc_oneshot_chan_cfg_t config = {
        .bitwidth = ADC_BITWIDTH_DEFAULT,
        .atten = ADC_ATTEN_DB_11, 
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc1_handle, LDR_ADC_CHAN, &config));
    ESP_LOGI(TAG, "ADC LDR initialized.");
}

// Task Utama
void sensor_task(void *pvParameters) {
    char gps_buffer[512];
    uint8_t rtc_sec;
    int ldr_val;

    while (1) {
        ESP_LOGI(TAG, "========== BACA SENSOR ==========");

        // 1. Baca LDR & Kontrol Relay
        if (adc_oneshot_read(adc1_handle, LDR_ADC_CHAN, &ldr_val) == ESP_OK) {
            ESP_LOGI(TAG, "[LDR] Raw ADC: %d", ldr_val);
            if (ldr_val < 500) { 
                gpio_set_level(RELAY_PIN, 1); 
                ESP_LOGI(TAG, "[RELAY] Terang - Menyambung daya AC ke Driver");
            } else { 
                gpio_set_level(RELAY_PIN, 0); 
                ESP_LOGI(TAG, "[RELAY] Gelap - Memutus daya AC ke Driver");
            }
        }

        // 2. Baca RTC
        if (rtc_read_seconds(&rtc_sec)) {
            ESP_LOGI(TAG, "[RTC] Detik (Hex): 0x%02x", rtc_sec);
        }

        // 3. Baca PZEM
        pzem_data_t pzem_data = pzem_read_registers();
        if (pzem_data.valid) {
            ESP_LOGI(TAG, "[PZEM] V: %.2f | I: %.3f | P: %.2f | E: %.3f", 
                     pzem_data.voltage, pzem_data.current, pzem_data.power, pzem_data.energy);
        } else {
            ESP_LOGW(TAG, "[PZEM] Gagal membaca data");
        }

        // 4. Baca GPS
        gps_read_info(gps_buffer, sizeof(gps_buffer));
        if (strlen(gps_buffer) > 0) {
            ESP_LOGI(TAG, "[GPS] Info: %s", gps_buffer);
        } else {
            ESP_LOGI(TAG, "[GPS] Tidak ada balasan");
        }

        ESP_LOGI(TAG, "=================================\n");
        vTaskDelay(pdMS_TO_TICKS(3000));
    }
}

void app_main(void) {
    ESP_LOGI(TAG, "System Booting...");
    
    // Inisialisasi semua periferal perangkat keras
    init_relay();
    init_adc_ldr();
    rtc_init();
    pzem_init();
    gps_init();

    xTaskCreate(sensor_task, "sensor_task", 8192, NULL, 5, NULL);
}