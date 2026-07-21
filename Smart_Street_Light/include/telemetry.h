#ifndef TELEMETRY_H
#define TELEMETRY_H

#include "mqtt_client.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "driver/uart.h"

#define WIFI_SSID           "xxxxx"
#define WIFI_PASS           "xxxxx"
#define MQTT_BROKER_URL     "tcp://broker.emqx.io:1883"
#define MQTT_TOPIC_PUB      "iot/lights/L-107/telemetry"

void send_telemetry_cellular(const char* id, const char* sector, uint32_t uptime, float volt, float current, float power, float lat, float lng, int alerts);
static void wifi_event_handler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data);
void send_telemetry(const char* id, const char* sector, uint32_t uptime, float volt, float current, float power, float lat, float lng, int alerts);
static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data);
void init_wifi(void);
void init_cellular_mqtt(void);
void init_mqtt(void);

#endif