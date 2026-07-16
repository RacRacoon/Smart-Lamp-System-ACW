#include "software_serial.h"
#include "driver/rmt_rx.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define BAUD_RATE 9600
#define BIT_DURATION_US (1000000 / BAUD_RATE) // Sekitar 104 us per bit

static const char *TAG = "GPS_CUSTOM_RX";
static rmt_channel_handle_t rx_channel = NULL;
static rmt_symbol_word_t raw_symbols[512]; // Buffer untuk sinyal listrik RMT

void gps_sw_serial_init(int rx_pin) {
    rmt_rx_channel_config_t rx_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 1000000, // Resolusi 1 MHz (1 tick = 1 mikrodetik)
        .mem_block_symbols = 256,
        .gpio_num = rx_pin,
    };
    ESP_ERROR_CHECK(rmt_new_rx_channel(&rx_config, &rx_channel));
    ESP_ERROR_CHECK(rmt_enable(rx_channel));
    ESP_LOGI(TAG, "Custom GPS Software Serial (RMT) diinisialisasi pada pin %d", rx_pin);
}

// Fungsi Internal: Mengubah sinyal listrik (durasi mikrosekon) menjadi Byte ASCII
static void decode_rmt_to_uart(rmt_symbol_word_t *symbols, size_t num_symbols, uint8_t *out_buf, size_t *out_len, size_t max_len) {
    int bit_count = 0;
    uint8_t current_byte = 0;
    int state = 0; // 0: Mencari Start Bit, 1: Membaca 8 Data Bit
    *out_len = 0;

    for (int i = 0; i < num_symbols; i++) {
        // RMT menyimpan sepasang sinyal (Level 0/1 dan Durasinya)
        for (int j = 0; j < 2; j++) {
            int level = (j == 0) ? symbols[i].active.level : symbols[i].active.level == 0 ? 1 : 0;
            int duration = (j == 0) ? symbols[i].active.duration : symbols[i].inactive.duration;
            
            if (duration == 0) continue;

            // Hitung ada berapa bit dalam durasi ini (dibulatkan)
            int bits = (duration + (BIT_DURATION_US / 2)) / BIT_DURATION_US;

            for (int b = 0; b < bits; b++) {
                if (state == 0) {
                    if (level == 0) { // Start bit UART selalu LOW (0)
                        state = 1;
                        bit_count = 0;
                        current_byte = 0;
                    }
                } else if (state == 1) {
                    if (bit_count < 8) {
                        // UART mengirim Least Significant Bit (LSB) lebih dulu
                        if (level) current_byte |= (1 << bit_count);
                        bit_count++;
                    } else { // Stop Bit tercapai
                        if (*out_len < max_len) {
                            out_buf[(*out_len)++] = current_byte;
                        }
                        state = 0; // Kembali mencari Start bit berikutnya
                    }
                }
            }
        }
    }
}

size_t gps_sw_serial_read(uint8_t *out_buffer, size_t max_len) {
    rmt_receive_config_t receive_config = {
        .signal_delay_max_ticks = 5000, // Anggap kalimat NMEA selesai jika diam selama 5ms
    };
    
    // Mulai mendengarkan pin RX
    if (rmt_receive(rx_channel, raw_symbols, sizeof(raw_symbols), &receive_config) == ESP_OK) {
        // Jika data diterima, dekode menjadi ASCII
        size_t len = 0;
        // Hitung jumlah simbol yang ditangkap
        size_t num_symbols = sizeof(raw_symbols) / sizeof(rmt_symbol_word_t); 
        decode_rmt_to_uart(raw_symbols, num_symbols, out_buffer, &len, max_len);
        return len;
    }
    return 0;
}