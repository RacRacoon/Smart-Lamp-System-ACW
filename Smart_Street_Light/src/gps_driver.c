#include "gps_driver.h"
#include <string.h>
#include "esp_log.h"

static const char *TAG = "GPS_DRIVER";

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
    
    // Nyalakan GPS pada Modem
    const char* gps_power_on = "AT+CGPS=1\r\n";
    uart_write_bytes(MODEM_UART_NUM, gps_power_on, strlen(gps_power_on));
    
    ESP_LOGI(TAG, "GPS Modem UART Initialized and Powered On");
}

void gps_read_info(char *buffer, size_t max_len) {
    const char* gps_get_info = "AT+CGPSINFO\r\n";
    
    uart_flush_input(MODEM_UART_NUM); 
    uart_write_bytes(MODEM_UART_NUM, gps_get_info, strlen(gps_get_info));
    vTaskDelay(pdMS_TO_TICKS(200)); // Tunggu modem merespons
    
    int len = uart_read_bytes(MODEM_UART_NUM, buffer, max_len - 1, pdMS_TO_TICKS(100));
    if (len > 0) {
        buffer[len] = '\0'; // Jadikan string valid
    } else {
        buffer[0] = '\0';   // Buffer kosong jika gagal
    }
}