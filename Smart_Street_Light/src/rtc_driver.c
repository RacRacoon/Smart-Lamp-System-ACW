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

void ds1307_set_time(uint8_t date, uint8_t month, uint8_t year, uint8_t hours, uint8_t minutes, uint8_t seconds) {
    uint8_t data[8];
    
    // Byte pertama selalu alamat register awal tujuan (0x00 = Register Detik)
    data[0] = 0x00; 
    
    // DS1307 menerima format BCD, kita konversi dari desimal
    // Catatan: Bit ke-7 dari detik adalah Clock Halt (CH). Memasukkan detik (0-59) 
    // dengan bit ke-7 bernilai 0 akan otomatis memastikan osilator RTC menyala.
    data[1] = dec_to_bcd(seconds);
    data[2] = dec_to_bcd(minutes);
    data[3] = dec_to_bcd(hours);
    
    // data[4] adalah register Hari/Day of week (1-7). 
    data[4] = 0x00; 
    
    data[5] = dec_to_bcd(date);
    data[6] = dec_to_bcd(month);
    data[7] = dec_to_bcd(year);

    // Kirim 8 byte sekaligus ke I2C
    esp_err_t err = i2c_master_write_to_device(I2C_MASTER_NUM, DS1307_ADDR, data, 8, pdMS_TO_TICKS(1000));
    
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "Waktu RTC berhasil di-set/dikalibrasi!");
    } else {
        ESP_LOGE(TAG, "Gagal meng-set waktu RTC! Cek koneksi kabel I2C.");
    }
}


// Membaca akumulasi Uptime Lampu dari NV-RAM RTC
uint32_t ds1307_read_uptime(void) {
    uint8_t start_reg = 0x08; // Alamat awal NV-RAM DS1307
    uint8_t data[4] = {0};
    
    esp_err_t err = i2c_master_write_read_device(I2C_MASTER_NUM, DS1307_ADDR, &start_reg, 1, data, 4, pdMS_TO_TICKS(100));
    
    if (err == ESP_OK) {
        uint32_t uptime = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3];
        // Jika memori masih kosong / baru (0xFFFFFFFF), anggap 0
        if (uptime == 0xFFFFFFFF) return 0; 
        return uptime;
    }
    return 0;
}

// Menulis akumulasi Uptime Lampu ke NV-RAM RTC
void ds1307_write_uptime(uint32_t uptime_sec) {
    uint8_t data[5];
    data[0] = 0x08; // Alamat register tujuan
    
    // Pecah nilai 32-bit menjadi 4 keping byte
    data[1] = (uptime_sec >> 24) & 0xFF;
    data[2] = (uptime_sec >> 16) & 0xFF;
    data[3] = (uptime_sec >> 8) & 0xFF;
    data[4] = uptime_sec & 0xFF;

    // SRAM = Aman ditulis terus-terusan setiap lampu menyala
    i2c_master_write_to_device(I2C_MASTER_NUM, DS1307_ADDR, data, 5, pdMS_TO_TICKS(100));
}

rtc_time_t rtc_read_time(void) {
    rtc_time_t time_data = {0};
    time_data.valid = false;
    
    uint8_t start_reg = 0x00; // Mulai baca dari Register 0x00 (Detik)
    uint8_t data[7];          // Kita cuma butuh 7 Byte (Detik sampai Tahun)

    // Meminta 7 byte secara langsung
    esp_err_t err = i2c_master_write_read_device(I2C_MASTER_NUM, DS1307_ADDR, &start_reg, 1, data, 7, pdMS_TO_TICKS(1000));
    
    if (err == ESP_OK) {
        // PERHATIKAN INDEXNYA DIMULAI DARI 0, DAN BITMASK JANGAN DIHAPUS
        time_data.seconds = data[0] & 0x7F; // Register 0x00 = Detik
        time_data.minutes = data[1];        // Register 0x01 = Menit
        time_data.hours   = data[2] & 0x3F; // Register 0x02 = Jam
        
        // data[3] adalah register Hari (1-7), tidak kita masukkan ke struct
        
        time_data.date    = data[4] & 0x3F; // Register 0x04 = Tanggal
        time_data.month   = data[5] & 0x1F; // Register 0x05 = Bulan
        time_data.year    = data[6];        // Register 0x06 = Tahun
        
        time_data.valid = true;
    } else {
        ESP_LOGW(TAG, "I2C Read Time Failed");
    }
    
    return time_data;
}