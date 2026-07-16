#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/uart.h"
#include "driver/i2c.h"
#include "esp_adc/adc_oneshot.h"

static const char *TAG = "SMART_LIGHT";

// ================= DEFINISI PIN =================
// 1. LDR Sensor
#define LDR_ADC_CHAN        ADC_CHANNEL_8 // GPIO9 adalah ADC1_CH8 di ESP32-S3
#define I2C_MASTER_NUM      I2C_NUM_0
#define DS1307_ADDR         0x68
// 3. PZEM-004T
#define PZEM_UART_NUM       UART_NUM_2

#define BUF_SIZE (1024)

// Handle untuk ADC
adc_oneshot_unit_handle_t adc1_handle;

// ================= FUNGSI INISIALISASI PERIFERAL =================

void init_adc_ldr() {
    adc_oneshot_unit_init_cfg_t init_config1 = {
        .unit_id = ADC_UNIT_1,
    };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&init_config1, &adc1_handle));

    adc_oneshot_chan_cfg_t config = {
        .bitwidth = ADC_BITWIDTH_DEFAULT,
        .atten = ADC_ATTEN_DB_11, // Attenuation 11dB untuk membaca hingga ~3.3V
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc1_handle, LDR_ADC_CHAN, &config));
    ESP_LOGI(TAG, "ADC untuk LDR (GPIO09) berhasil diinisialisasi.");
}

void init_i2c_rtc() {
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = I2C_MASTER_SDA_IO,
        .scl_io_num = I2C_MASTER_SCL_IO,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 100000,
    };
    i2c_param_config(I2C_MASTER_NUM, &conf);
    i2c_driver_install(I2C_MASTER_NUM, conf.mode, 0, 0, 0);
    ESP_LOGI(TAG, "I2C untuk RTC (GPIO02, GPIO03) berhasil diinisialisasi.");
}

void init_hardware_uart_pzem() {
    uart_config_t uart_config = {
        .baud_rate = 9600,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE
    };
    uart_param_config(PZEM_UART_NUM, &uart_config);
    uart_set_pin(PZEM_UART_NUM, PZEM_TX_PIN, PZEM_RX_PIN, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    uart_driver_install(PZEM_UART_NUM, BUF_SIZE, 0, 0, NULL, 0);
    ESP_LOGI(TAG, "Hardware UART2 untuk PZEM (GPIO15, GPIO16) berhasil diinisialisasi.");
}


// ================= TASK UTAMA (BACA SENSOR) =================

void sensor_task(void *pvParameters) {
    uint8_t gps_data[256];
    uint8_t pzem_data[256];
    int ldr_val;
    uint8_t rtc_reg = 0x00; // Register detik pada DS1307
    uint8_t rtc_sec;

    // Payload Modbus RTU untuk membaca tegangan dari PZEM (Format Baku)
    uint8_t pzem_request[] = {0x01, 0x04, 0x00, 0x00, 0x00, 0x0A, 0x70, 0x0D};

    while (1) {
        ESP_LOGI(TAG, "========== MEMBACA SEMUA SENSOR ==========");

        // --- 1. LDR Sensor (Analog) ---
        if (adc_oneshot_read(adc1_handle, LDR_ADC_CHAN, &ldr_val) == ESP_OK) {
            ESP_LOGI(TAG, "[LDR] Raw ADC: %d", ldr_val);
        }

        // --- 2. RTC DS1307 (I2C) ---
        esp_err_t err = i2c_master_write_read_device(I2C_MASTER_NUM, DS1307_ADDR, &rtc_reg, 1, &rtc_sec, 1, 1000 / portTICK_PERIOD_MS);
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "[RTC] Detik (Hex BCD): 0x%02x", rtc_sec);
        } else {
            ESP_LOGW(TAG, "[RTC] Gagal membaca I2C.");
        }

        // --- 3. PZEM-004T (Hardware UART2) ---
        // Kirim request Modbus
        uart_write_bytes(PZEM_UART_NUM, (const char *)pzem_request, sizeof(pzem_request));
        vTaskDelay(pdMS_TO_TICKS(100)); // Beri waktu PZEM memproses
        
        // Baca balasan
        int pzem_len = uart_read_bytes(PZEM_UART_NUM, pzem_data, (sizeof(pzem_data) - 1), 50 / portTICK_PERIOD_MS);
        if (pzem_len > 0) {
            ESP_LOGI(TAG, "[PZEM] Balasan Modbus Diterima (%d bytes).", pzem_len);
        } else {
            ESP_LOGW(TAG, "[PZEM] Timeout / Tidak ada respons.");
        }

        // --- 4. GPS NEO-M8N (Custom Software Serial) ---
        size_t gps_len = gps_sw_serial_read(gps_data, sizeof(gps_data) - 1);
        if (gps_len > 0) {
            gps_data[gps_len] = '\0'; // Jadikan string valid
            ESP_LOGI(TAG, "[GPS] NMEA ditangkap (%d bytes):", gps_len);
            printf("%s\n", gps_data); // Print string NMEA ke terminal
        } else {
            ESP_LOGI(TAG, "[GPS] Belum ada data NMEA.");
        }

        ESP_LOGI(TAG, "==========================================\n");
        vTaskDelay(pdMS_TO_TICKS(3000)); // Jeda 3 detik agar terminal mudah dibaca
    }
}

void app_main(void) {
    ESP_LOGI(TAG, "Booting Smart Pole System...");
    
    // 1. Inisialisasi Perangkat Keras Utama
    init_adc_ldr();
    init_i2c_rtc();
    init_hardware_uart_pzem();

    // 2. Inisialisasi Library Custom GPS (RMT Software Serial)
    gps_sw_serial_init(GPS_RX_PIN);

    // 3. Jalankan FreeRTOS Task
    xTaskCreate(sensor_task, "sensor_task", 8192, NULL, 5, NULL);
}
