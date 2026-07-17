#include "rtc_driver.h"
#include "esp_log.h"

static const char *TAG = "RTC_DRIVER";

void i2c_scanner() {
    ESP_LOGI(TAG, "==========================================");
    ESP_LOGI(TAG, "        MEMULAI SCANNER I2C...            ");
    
    uint8_t count = 0;
    
    for (uint8_t i = 1; i < 127; i++) {
        // Membuat paket perintah I2C (Hanya mengetuk / ping alamat)
        i2c_cmd_handle_t cmd = i2c_cmd_link_create();
        i2c_master_start(cmd);
        i2c_master_write_byte(cmd, (i << 1) | I2C_MASTER_WRITE, true);
        i2c_master_stop(cmd);
        
        // Eksekusi perintah
        esp_err_t ret = i2c_master_cmd_begin(I2C_MASTER_NUM, cmd, 50 / portTICK_PERIOD_MS);
        i2c_cmd_link_delete(cmd);
        
        if (ret == ESP_OK) {
            ESP_LOGI(TAG, ">>> Perangkat I2C TERDETEKSI di Alamat: 0x%02x <<<", i);
            count++;
        }
    }
    
    if (count == 0) {
        ESP_LOGE(TAG, "GAGAL: Tidak ada perangkat I2C yang membalas!");
    } else {
        ESP_LOGI(TAG, "Total perangkat ditemukan: %d", count);
    }
    ESP_LOGI(TAG, "==========================================");
}

void ds1307_init(void) {
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

// Fungsi internal untuk mengubah angka desimal (10) menjadi BCD (0x10)
static uint8_t dec_to_bcd(uint8_t val) {
    return ((val / 10 * 16) + (val % 10));
}

void ds1307_set_time(uint8_t hours, uint8_t minutes, uint8_t seconds) {
    uint8_t data[4];
    data[0] = 0x00; // Alamat register awal (0x00 = Seconds)
    data[1] = dec_to_bcd(seconds); // Akan menimpa bit CH menjadi 0 (Osilator ON)
    data[2] = dec_to_bcd(minutes);
    data[3] = dec_to_bcd(hours);

    // Tulis ke perangkat (Menimpa register detik, menit, jam sekaligus)
    esp_err_t err = i2c_master_write_to_device(I2C_MASTER_NUM, DS1307_ADDR, data, 4, pdMS_TO_TICKS(1000));
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "Waktu berhasil disetel dan Osilator Dihidupkan!");
    } else {
        ESP_LOGW(TAG, "Gagal menyetel waktu I2C.");
    }
}

// ... [Biarkan fungsi ds1307_init dan ds1307_set_time tetap seperti sebelumnya] ...

rtc_time_t rtc_read_time(void) {
    rtc_time_t time_data = {0};
    time_data.valid = false;
    
    uint8_t start_reg = 0x00; // Mulai baca dari Register 0x00 (Detik)
    uint8_t data[3];          // Buffer untuk menampung [Detik, Menit, Jam]

    // Meminta 3 byte secara langsung
    esp_err_t err = i2c_master_write_read_device(I2C_MASTER_NUM, DS1307_ADDR, &start_reg, 1, data, 3, pdMS_TO_TICKS(1000));
    
    if (err == ESP_OK) {
        // data[0] = Detik (Kita mask dengan 0x7F untuk membuang bit CH jika terbaca)
        time_data.seconds = data[0] & 0x7F; 
        
        // data[1] = Menit
        time_data.minutes = data[1];        
        
        // data[2] = Jam (Kita mask dengan 0x3F untuk membuang bit format 12/24 jam)
        time_data.hours   = data[2] & 0x3F; 
        
        time_data.valid = true;
    } else {
        ESP_LOGW(TAG, "I2C Read Time Failed");
    }
    
    return time_data;
}