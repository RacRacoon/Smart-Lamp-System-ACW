#ifndef SOFTWARE_SERIAL_H
#define SOFTWARE_SERIAL_H

#include <stdint.h>
#include <stddef.h>

// Inisialisasi pin RX untuk GPS menggunakan RMT
void gps_sw_serial_init(int rx_pin);

// Membaca kalimat NMEA dari GPS
// return: jumlah byte yang berhasil dibaca (0 jika tidak ada)
size_t gps_sw_serial_read(uint8_t *out_buffer, size_t max_len);

#endif // SOFTWARE_SERIAL_H