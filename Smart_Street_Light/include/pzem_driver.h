#ifndef PZEM_DRIVER_H
#define PZEM_DRIVER_H

#include <stdint.h>
#include <stdbool.h>
#include "driver/uart.h"

#define PZEM_TXD_PIN    16
#define PZEM_RXD_PIN    15
#define UART_PORT_NUM   UART_NUM_2

// Struktur data PZEM sesuai permintaanmu
typedef struct {
    float voltage;
    float current;
    float power;
    float energy;
    float frequency;
    float pf;
    bool valid;
} pzem_data_t;

void pzem_init(void);
pzem_data_t pzem_read_registers(void);

#endif 