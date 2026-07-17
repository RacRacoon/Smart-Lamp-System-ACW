#include "pzem_driver.h"
#include <string.h>
#include "esp_log.h"
#include <math.h>

static const char *TAG = "PZEM_DRIVER";
#define BUF_SIZE 128

// Internal CRC Helper
static uint16_t calculate_crc(const uint8_t *data, uint16_t len) {
    uint16_t crc = 0xFFFF;
    for (int pos = 0; pos < len; pos++) {
        crc ^= (uint16_t)data[pos];
        for (int i = 8; i != 0; i--) {
            if ((crc & 0x0001) != 0) crc = (crc >> 1) ^ 0xA001;
            else crc >>= 1;
        }
    }
    return crc;
}

static float roundto4(float value) {
    return roundf(value * 10000.0f) / 10000.0f;
}

void pzem_init(void) {
    uart_config_t uart_config = {
        .baud_rate = 9600,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART_PORT_NUM, BUF_SIZE * 2, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART_PORT_NUM, &uart_config));
    ESP_ERROR_CHECK(uart_set_pin(UART_PORT_NUM, PZEM_TXD_PIN, PZEM_RXD_PIN, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    ESP_LOGI(TAG, "PZEM UART Initialized");
}

pzem_data_t pzem_read_registers(void) {
    pzem_data_t result = {0};
    result.valid = false;

    uart_flush_input(UART_PORT_NUM);
    
    // Modbus Command 0x04 Read 10 Registers (Address 0xF8)
    uint8_t request[] = {0xF8, 0x04, 0x00, 0x00, 0x00, 0x0A, 0x64, 0x64};
    uart_write_bytes(UART_PORT_NUM, (const char *)request, 8);

    uint8_t data[32];
    int len = uart_read_bytes(UART_PORT_NUM, data, 25, pdMS_TO_TICKS(100));

    if (len >= 25) {
        uint16_t received_crc = (data[24] << 8) | data[23];
        if (received_crc == calculate_crc(data, 23)) {
            result.voltage = roundto4(((data[3] << 8) | data[4]) / 10.0);
            
            uint32_t c_low = (data[5] << 8) | data[6];
            uint32_t c_high = (data[7] << 8) | data[8];
            result.current = roundto4(((c_high << 16) | c_low) / 1000.0); // mA -> A
            
            uint32_t p_low = (data[9] << 8) | data[10];
            uint32_t p_high = (data[11] << 8) | data[12];
            result.power = roundto4(((p_high << 16) | p_low) / 10.0);
            
            uint32_t e_low = (data[13] << 8) | data[14];
            uint32_t e_high = (data[15] << 8) | data[16];
            result.energy = roundto4(((e_high << 16) | e_low)/ 1000.0);
            
            result.frequency = ((data[17] << 8) | data[18]) / 10.0;
            result.pf = roundto4(((data[19] << 8) | data[20]) / 100.0);
            
            result.valid = true;
        } else {
            ESP_LOGW(TAG, "CRC Error");
        }
    }
    return result;
}