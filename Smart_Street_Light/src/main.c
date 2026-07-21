#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "nvs_flash.h" // WAJIB UNTUK WI-FI

// Include custom drivers
#include "pzem_driver.h"
#include "rtc_driver.h"
#include "gps_driver.h"
#include "telemetry.h"
#include <time.h>

static const char *TAG = "MAIN_APP";

SemaphoreHandle_t uart1_mutex = NULL;


#define RELAY_PIN       47
#define LDR_ADC_CHAN    ADC_CHANNEL_8 // GPIO9

adc_oneshot_unit_handle_t adc1_handle;
uint32_t total_lampu_nyala_sec;

pzem_data_t global_pzem_data = {0}; 

typedef enum {
    SENSOR_STATE_READ_DATA,
    SENSOR_STATE_EVALUATE,
    SENSOR_STATE_IDLE
}sensor_state_t;

typedef enum {
    TEL_STATE_INIT_MODEM,
    TEL_STATE_PUBLISH,
    TEL_STATE_IDLE
} telemetry_state_t;

typedef struct {
    uint16_t year;
    uint8_t  month;
    uint8_t  date;
    uint8_t  hour;
    uint8_t  minute;
    uint8_t  second;
} install_time_t;

const install_time_t WAKTU_INSTALASI = {
    .year   = 2026,
    .month  = 7,
    .date   = 17,
    .hour   = 14,
    .minute = 37,
    .second = 10
};

static uint8_t bcd_to_dec(uint8_t val) {
    return ((val / 16 * 10) + (val % 16));
}

static time_t get_installation_epoch(install_time_t setup_time) {
    struct tm timeinfo = {0};
    timeinfo.tm_year = setup_time.year - 1900; 
    timeinfo.tm_mon  = setup_time.month - 1;   
    timeinfo.tm_mday = setup_time.date;
    timeinfo.tm_hour = setup_time.hour;
    timeinfo.tm_min  = setup_time.minute;
    timeinfo.tm_sec  = setup_time.second;
    return mktime(&timeinfo);
}

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
    sensor_state_t current_state = SENSOR_STATE_READ_DATA;
    
    char gps_buffer[512];
    int ldr_val = 0;
    bool pzem_menyala = false;
    
    total_lampu_nyala_sec = ds1307_read_uptime();
    time_t epoch_sebelumnya = 0;

    rtc_time_t init_rtc = rtc_read_time();
    if (init_rtc.valid) {
        epoch_sebelumnya = rtc_to_epoch(init_rtc);
    }

    while (1) {
        switch (current_state) {
            case SENSOR_STATE_READ_DATA:
                ESP_LOGI(TAG, "========== BACA SENSOR ==========");
                
                // 1. Baca LDR
                if (adc_oneshot_read(adc1_handle, LDR_ADC_CHAN, &ldr_val) == ESP_OK) {
                    ESP_LOGI(TAG, "[LDR] Raw ADC: %d", ldr_val);
                }
                
                // 2. Baca PZEM
                global_pzem_data = pzem_read_registers(); 
                pzem_menyala = global_pzem_data.valid;
                if (pzem_menyala) {
                    ESP_LOGI(TAG, "[PZEM] V: %.2f | I: %.3f | P: %.2f", global_pzem_data.voltage, global_pzem_data.current, global_pzem_data.power);
                } else {
                    ESP_LOGW(TAG, "[PZEM] Gagal membaca data (Lampu Mati)");
                }

                // 3. Baca GPS
                gps_read_info(gps_buffer, sizeof(gps_buffer));
                if (strlen(gps_buffer) > 0) {
                    ESP_LOGI(TAG, "[GPS] Info: %s", gps_buffer);
                }
                
                current_state = SENSOR_STATE_EVALUATE;
                break;

            case SENSOR_STATE_EVALUATE:
                // Evaluasi Relay LDR
                if (ldr_val < 500) { 
                    gpio_set_level(RELAY_PIN, 0); 
                    ESP_LOGI(TAG, "[RELAY] Terang - Mematikan AC");
                } else { 
                    gpio_set_level(RELAY_PIN, 1); 
                    ESP_LOGI(TAG, "[RELAY] Gelap - Menyalakan AC");
                }

                // Kalkulasi Waktu
                rtc_time_t current_rtc = rtc_read_time();
                if (current_rtc.valid) {
                    time_t epoch_sekarang = rtc_to_epoch(current_rtc);
                    if (epoch_sebelumnya > 0 && epoch_sekarang >= epoch_sebelumnya) {
                        if (pzem_menyala) {
                            total_lampu_nyala_sec += (uint32_t)(epoch_sekarang - epoch_sebelumnya);
                            ds1307_write_uptime(total_lampu_nyala_sec);
                        }
                    }
                    epoch_sebelumnya = epoch_sekarang;
                    
                    uint32_t up_hari  = total_lampu_nyala_sec / 86400;
                    uint32_t sisa     = total_lampu_nyala_sec % 86400;
                    ESP_LOGI(TAG, "[SYSTEM] UPTIME: %lu Hari, %02lu:%02lu:%02lu", up_hari, (sisa/3600), ((sisa%3600)/60), (sisa%60));
                }
                
                ESP_LOGI(TAG, "=================================\n");
                current_state = SENSOR_STATE_IDLE;
                break;

            case SENSOR_STATE_IDLE:
                vTaskDelay(pdMS_TO_TICKS(3000));
                current_state = SENSOR_STATE_READ_DATA; // Ulangi siklus
                break;
        }
    }
}

void telemetry_task(void *pvParameters)
{
    telemetry_state_t current_state = TEL_STATE_INIT_MODEM;
    
    const char* id = "L-107";
    const char* sector = "Sektor 2 (Kertajaya)";
    float lat = -7.284814;  
    float lng = 112.794833;
    int alerts = 0;

    while (1) {
        switch (current_state) {
            case TEL_STATE_INIT_MODEM:
                ESP_LOGI(TAG, "Menunggu 15 detik agar modem mendapat sinyal seluler...");
                vTaskDelay(pdMS_TO_TICKS(15000)); 
                init_cellular_mqtt();
                
                // Jika ingin lebih canggih, cek jika gagal init, kembalikan ke INIT.
                // Sementara ini kita asumsikan sukses dan lanjut.
                current_state = TEL_STATE_PUBLISH;
                break;

            case TEL_STATE_PUBLISH:
                ESP_LOGI(TAG, "Mempublikasikan data MQTT...");
                send_telemetry_cellular(id, sector, total_lampu_nyala_sec, 
                                        global_pzem_data.voltage, global_pzem_data.current, 
                                        global_pzem_data.power, lat, lng, alerts);
                
                current_state = TEL_STATE_IDLE;
                break;

            case TEL_STATE_IDLE:
                vTaskDelay(pdMS_TO_TICKS(5000));
                current_state = TEL_STATE_PUBLISH; // Kembali kirim data
                break;
        }
    }
}

void app_main(void) {
    ESP_LOGI(TAG, "System Booting...");
    
    // 1. Inisialisasi Memori NVS (Wajib untuk Wi-Fi)
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    uart1_mutex = xSemaphoreCreateMutex();
    // 2. Inisialisasi Jaringan (Wi-Fi & MQTT)
    //init_wifi();
    //init_mqtt();

    // 3. Inisialisasi Perangkat Keras
    init_relay();
    init_adc_ldr();
    ds1307_init();  

     //ds1307_set_time(

// WAKTU_INSTALASI.date,

// WAKTU_INSTALASI.month,

// WAKTU_INSTALASI.year - 2000,

// WAKTU_INSTALASI.hour,

// WAKTU_INSTALASI.minute,

// WAKTU_INSTALASI.second

//);

//ds1307_write_uptime(0); 

init_relay();
    init_adc_ldr();
    ds1307_init();  
    pzem_init();
    gps_init();
    // 4. Jalankan Multitasking
    xTaskCreate(sensor_task, "sensor_task", 8192, NULL, 5, NULL);
    xTaskCreate(telemetry_task, "telemetry_task", 8192, NULL, 6, NULL);
}