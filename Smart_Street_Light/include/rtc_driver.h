#ifndef RTC_DRIVER_H
#define RTC_DRIVER_H

#include <stdint.h>
#include <stdbool.h>
#include "driver/i2c.h"

#define I2C_MASTER_SCL_IO   2
#define I2C_MASTER_SDA_IO   3
#define I2C_MASTER_NUM      I2C_NUM_0
#define DS1307_ADDR         0x68

// Struktur untuk menampung waktu secara lengkap
typedef struct {
    uint8_t year;
    uint8_t month;
    uint8_t date;
    uint8_t hours;
    uint8_t minutes;
    uint8_t seconds;
    bool valid;
} rtc_time_t;


void ds1307_init(void);
void ds1307_set_time(uint8_t date, uint8_t month, uint8_t year, uint8_t hours, uint8_t minutes, uint8_t seconds);

// Fungsi pembacaan waktu (menggantikan rtc_read_seconds yang lama)
rtc_time_t rtc_read_time(void);
// Fungsi NV-RAM untuk Odometer (Lifetime Uptime)
uint32_t ds1307_read_uptime(void);
void ds1307_write_uptime(uint32_t uptime_sec);

#endif // RTC_DRIVER_H