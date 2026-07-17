#include "gps_driver.h"
#include <string.h>
#include "esp_log.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "GPS_DRIVER";

// Dari Datasheet LilyGo T-SIM7670G-S3:
#define MODEM_PWKEY_PIN  46 

void gps_init(void) {
    uart_config_t uart_config = {
        .baud_rate = 115200, 
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE
    };
    ESP_ERROR_CHECK(uart_driver_install(MODEM_UART_NUM, MODEM_BUF_SIZE, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(MODEM_UART_NUM, &uart_config));
    ESP_ERROR_CHECK(uart_set_pin(MODEM_UART_NUM, MODEM_TX_PIN, MODEM_RX_PIN, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    
    // --- 1. MENYALAKAN MODEM (Toggle PWRKEY GPIO46) ---
    gpio_config_t io_conf = {
        .intr_type = GPIO_INTR_DISABLE,
        .mode = GPIO_MODE_OUTPUT,
        .pin_bit_mask = (1ULL << MODEM_PWKEY_PIN),
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .pull_up_en = GPIO_PULLUP_DISABLE
    };
    gpio_config(&io_conf);

    ESP_LOGI(TAG, "Menekan tombol Power Modem (PWRKEY GPIO46)...");
    gpio_set_level(MODEM_PWKEY_PIN, 0);
    vTaskDelay(pdMS_TO_TICKS(100));
    gpio_set_level(MODEM_PWKEY_PIN, 1);
    vTaskDelay(pdMS_TO_TICKS(1000)); // Tahan PWRKEY selama 1 detik
    gpio_set_level(MODEM_PWKEY_PIN, 0); // Lepas tombol
    
    ESP_LOGI(TAG, "Menunggu OS Modem Booting (4 detik)...");
    vTaskDelay(pdMS_TO_TICKS(4000)); // Beri waktu OS modem untuk hidup penuh

    // --- 2. MENYALAKAN DAYA ANTENA GPS (AT Command) ---
    // Sesuai datasheet: AT+CGDRT=1,1 lalu AT+CGSETV=1,1
    const char* ant_pwr_1 = "AT+CGDRT=1,1\r\n";
    uart_write_bytes(MODEM_UART_NUM, ant_pwr_1, strlen(ant_pwr_1));
    vTaskDelay(pdMS_TO_TICKS(200));

    const char* ant_pwr_2 = "AT+CGSETV=1,1\r\n";
    uart_write_bytes(MODEM_UART_NUM, ant_pwr_2, strlen(ant_pwr_2));
    vTaskDelay(pdMS_TO_TICKS(200));

    // --- 3. MENYALAKAN MESIN GPS (AT Command) ---
    const char* gps_power_on = "AT+CGPS=1\r\n";
    uart_write_bytes(MODEM_UART_NUM, gps_power_on, strlen(gps_power_on));
    vTaskDelay(pdMS_TO_TICKS(200));
    
    ESP_LOGI(TAG, "Modem dan Antena GPS berhasil dihidupkan!");
}

void gps_read_info(char *buffer, size_t max_len) {
    const char* gps_get_info = "AT+CGPSINFO\r\n";
    
    uart_flush_input(MODEM_UART_NUM); 
    uart_write_bytes(MODEM_UART_NUM, gps_get_info, strlen(gps_get_info));
    vTaskDelay(pdMS_TO_TICKS(200)); // Tunggu modem merespons
    
    int len = uart_read_bytes(MODEM_UART_NUM, buffer, max_len - 1, pdMS_TO_TICKS(100));
    if (len > 0) {
        buffer[len] = '\0'; // Jadikan string valid
        
        // Membersihkan karakter newline/carriage return berlebih dari balasan AT Command
        char *newline = strchr(buffer, '\n');
        if (newline) *newline = '\0';
        char *cr = strchr(buffer, '\r');
        if (cr) *cr = '\0';
        
    } else {
        buffer[0] = '\0';   // Buffer kosong jika gagal
    }
}