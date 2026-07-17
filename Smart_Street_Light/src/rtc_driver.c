#include "rtc_driver.h"
#include "esp_log.h"

static const char *TAG = "RTC_DRIVER";

void rtc_init(void) {
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = I2C_MASTER_SDA_IO,
        .scl_io_num = I2C_MASTER_SCL_IO,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 100000,
    };
    ESP_ERROR_CHECK(i2c_param_config(I2C_MASTER_NUM, &conf));
    ESP_ERROR_CHECK(i2c_driver_install(I2C_MASTER_NUM, conf.mode, 0, 0, 0));
    ESP_LOGI(TAG, "RTC I2C Initialized");
}

bool rtc_read_seconds(uint8_t *seconds) {
    uint8_t rtc_reg = 0x00; 
    esp_err_t err = i2c_master_write_read_device(I2C_MASTER_NUM, DS1307_ADDR, &rtc_reg, 1, seconds, 1, pdMS_TO_TICKS(1000));
    if (err == ESP_OK) {
        return true;
    }
    ESP_LOGW(TAG, "I2C Read Failed");
    return false;
}