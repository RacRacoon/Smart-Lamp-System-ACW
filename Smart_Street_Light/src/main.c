#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "nvs_flash.h"

// Include custom drivers
#include "pzem_driver.h"
#include "rtc_driver.h"
#include "gps_driver.h"
#include "telemetry.h"
#include <time.h>



static const char *TAG = "MAIN_APP";

#define RELAY_PIN       47
#define LDR_ADC_CHAN    ADC_CHANNEL_8 // GPIO9

adc_oneshot_unit_handle_t adc1_handle;
uint32_t total_lampu_nyala_sec;

typedef struct {
    uint16_t year;
    uint8_t  month;
    uint8_t  date;
    uint8_t  hour;
    uint8_t  minute;
    uint8_t  second;
} install_time_t;

// ========================================================
// 2. HARDCODE WAKTU INSTALASI (WAKTU NOL) DI DALAM STRUCT
// ========================================================
const install_time_t WAKTU_INSTALASI = {
    .year   = 2026,
    .month  = 7,
    .date   = 17,
    .hour   = 14,
    .minute = 37,
    .second = 10
};

// Helper konversi BCD 
static uint8_t bcd_to_dec(uint8_t val) {
    return ((val / 16 * 10) + (val % 16));
}

// Fungsi internal untuk membuat UNIX Epoch langsung dari struct
static time_t get_installation_epoch(install_time_t setup_time) {
    struct tm timeinfo = {0};
    timeinfo.tm_year = setup_time.year - 1900; // Library time.h dihitung dari 1900
    timeinfo.tm_mon  = setup_time.month - 1;   // Bulan dimulai dari 0 (Jan = 0)
    timeinfo.tm_mday = setup_time.date;
    timeinfo.tm_hour = setup_time.hour;
    timeinfo.tm_min  = setup_time.minute;
    timeinfo.tm_sec  = setup_time.second;
    return mktime(&timeinfo);
}

// Helper untuk mengubah Kalender RTC menjadi UNIX Epoch
static time_t rtc_to_epoch(rtc_time_t rtc) {
    struct tm timeinfo = {0};
    timeinfo.tm_year = bcd_to_dec(rtc.year) + 2000 - 1900; 
    timeinfo.tm_mon  = bcd_to_dec(rtc.month) - 1; 
    timeinfo.tm_mday = bcd_to_dec(rtc.date);
    timeinfo.tm_hour = bcd_to_dec(rtc.hours);
    timeinfo.tm_min  = bcd_to_dec(rtc.minutes);
    timeinfo.tm_sec  = bcd_to_dec(rtc.seconds);
    return mktime(&timeinfo); 
}

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
        .atten = ADC_ATTEN_DB_12, 
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc1_handle, LDR_ADC_CHAN, &config));
    ESP_LOGI(TAG, "ADC LDR initialized.");
}

void sensor_task(void *pvParameters) {
    char gps_buffer[512];
    int ldr_val;
    
    // 1. Tarik riwayat Odometer Lampu dari memori baterai RTC saat alat baru nyala
    total_lampu_nyala_sec = ds1307_read_uptime();
    time_t epoch_sebelumnya = 0;

    // Ambil epoch awal sebagai titik start
    rtc_time_t init_rtc = rtc_read_time();
    if (init_rtc.valid) {
        epoch_sebelumnya = rtc_to_epoch(init_rtc);
    }

    while (1) {
        ESP_LOGI(TAG, "========== BACA SENSOR ==========");

        // 1. BACA LDR & KONTROL RELAY
        if (adc_oneshot_read(adc1_handle, LDR_ADC_CHAN, &ldr_val) == ESP_OK) {
            ESP_LOGI(TAG, "[LDR] Raw ADC: %d", ldr_val);
            if (ldr_val < 500) { 
                gpio_set_level(RELAY_PIN, 0); 
                ESP_LOGI(TAG, "[RELAY] Terang - Mematikan daya AC ke Driver");
            } else { 
                gpio_set_level(RELAY_PIN, 1); 
                ESP_LOGI(TAG, "[RELAY] Gelap - Menyalakan daya AC ke Driver");
            }
        }

        // 2. BACA PZEM (INDIKATOR UTAMA LAMPU NYALA)
        bool pzem_menyala = false;
        pzem_data_t pzem_data = pzem_read_registers();
        
        if (pzem_data.valid) {
            ESP_LOGI(TAG, "[PZEM] V: %.2f | I: %.3f | P: %.2f | E: %.3f", 
                     pzem_data.voltage, pzem_data.current, pzem_data.power, pzem_data.energy);
            pzem_menyala = true; // PZEM membalas = Daya masuk ke lampu
        } else {
            ESP_LOGW(TAG, "[PZEM] Gagal membaca data (Lampu/Driver Mati)");
        }

        // 3. KALKULASI UPTIME LAMPU (STOPWATCH)
        rtc_time_t current_rtc = rtc_read_time();
        if (current_rtc.valid) {
            time_t epoch_sekarang = rtc_to_epoch(current_rtc);
            
            // Hitung berapa detik berlalu sejak loop terakhir
            if (epoch_sebelumnya > 0 && epoch_sekarang >= epoch_sebelumnya) {
                uint32_t selisih_detik = (uint32_t)(epoch_sekarang - epoch_sebelumnya);
                
                // JIKA LAMPU MENYALA, TAMBAHKAN WAKTU KE TOTAL ODOMETER
                if (pzem_menyala) {
                    total_lampu_nyala_sec += selisih_detik;
                    
                    // Simpan langsung ke memori abadi RTC (Aman 0% keausan memori ESP32)
                    ds1307_write_uptime(total_lampu_nyala_sec);
                }
            }
            // Update titik waktu untuk loop berikutnya
            epoch_sebelumnya = epoch_sekarang;

            // --- FORMAT TAMPILAN ---
            uint32_t up_hari  = total_lampu_nyala_sec / 86400;
            uint32_t sisa     = total_lampu_nyala_sec % 86400;
            uint32_t up_jam   = sisa / 3600;
            sisa              = sisa % 3600;
            uint32_t up_menit = sisa / 60;
            uint32_t up_detik = sisa % 60;

            ESP_LOGI(TAG, "[SYSTEM] UPTIME LAMPU: %lu Hari, %02lu:%02lu:%02lu", up_hari, up_jam, up_menit, up_detik);
            ESP_LOGI(TAG, "[RTC] Waktu Aktual: 20%02d-%02d-%02d %02d:%02d:%02d", 
                     bcd_to_dec(current_rtc.year), bcd_to_dec(current_rtc.month), bcd_to_dec(current_rtc.date),
                     bcd_to_dec(current_rtc.hours), bcd_to_dec(current_rtc.minutes), bcd_to_dec(current_rtc.seconds));
        }

        // 4. BACA GPS
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

void telemetry_task(void *pvParameters)
{
    char json_payload[512]; // Buffer untuk menampung teks JSON

    // Hardcode data sesuai permintaan
    const char* id = "L-107";
    const char* sector = "Sektor 2 (Kertajaya - Depan ITS)";
    float lat = -7.284814;  // Koordinat Teknik Elektro ITS
    float lng = 112.794833;
    int alerts = 1;

    while (1) {
        pzem_data_t pzem_data = pzem_read_registers();

        ESP_LOGI(TAG, "Mempublikasikan data ke topik %s", MQTT_TOPIC_PUB);
        ESP_LOGI(TAG, "Payload:\n%s", json_payload);
        send_telemetry( id, sector, 
                       total_lampu_nyala_sec / 3600, // Konversi detik ke jam
                       pzem_data.voltage, pzem_data.current, pzem_data.power, 
                       lat, lng, alerts);

        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

void app_main(void) {
    ESP_LOGI(TAG, "System Booting...");
    
    init_relay();
    init_adc_ldr();
    ds1307_init();

    //ds1307_set_time(
    //    WAKTU_INSTALASI.date, 
    //    WAKTU_INSTALASI.month, 
    //    WAKTU_INSTALASI.year - 2000,
    //    WAKTU_INSTALASI.hour, 
    //    WAKTU_INSTALASI.minute, 
    //    WAKTU_INSTALASI.second
    //);
    //ds1307_write_uptime(0);
    pzem_init();
    gps_init();

    xTaskCreate(sensor_task, "sensor_task", 8192, NULL, 5, NULL);
    xTaskCreate(telemetry_task, "telemetry_task", 8192, NULL, 6, NULL);
}