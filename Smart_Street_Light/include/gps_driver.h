#ifndef GPS_DRIVER_H
#define GPS_DRIVER_H

#include <stddef.h>
#include "driver/uart.h"

#define MODEM_UART_NUM      UART_NUM_1
#define MODEM_TX_PIN        4 
#define MODEM_RX_PIN        5 
#define MODEM_BUF_SIZE      1024

void gps_init(void);
void gps_read_info(char *buffer, size_t max_len);

#endif // GPS_DRIVER_H