#ifndef RTC_DRIVER_H
#define RTC_DRIVER_H

#include <stdint.h>
#include <stdbool.h>
#include "driver/i2c.h"

#define I2C_MASTER_SCL_IO   2
#define I2C_MASTER_SDA_IO   3
#define I2C_MASTER_NUM      I2C_NUM_0
#define DS1307_ADDR         0x68

void rtc_init(void);
bool rtc_read_seconds(uint8_t *seconds);

#endif // RTC_DRIVER_H