#include "telemetry.h"
#include "esp_log.h"

static const char *TAG = "SMART_POLE_WIFI_MQTT";

static EventGroupHandle_t wifi_event_group;
const int WIFI_CONNECTED_BIT = BIT0;

esp_mqtt_client_handle_t mqtt_client = NULL;

// ========================================================
// EVENT HANDLER (Wi-Fi & MQTT)
// ========================================================
static void wifi_event_handler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Terputus dari Wi-Fi, mencoba menyambung kembali...");
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "Berhasil mendapat IP: " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    esp_mqtt_event_handle_t event = event_data;
    switch ((esp_mqtt_event_id_t)event_id) {
        case MQTT_EVENT_CONNECTED:
            ESP_LOGI(TAG, "MQTT Terhubung ke Broker!");
            break;
        case MQTT_EVENT_DISCONNECTED:
            ESP_LOGW(TAG, "MQTT Terputus dari Broker.");
            break;
        default:
            break;
    }
}

// ========================================================
// INISIALISASI WI-FI & MQTT
// ========================================================
void init_wifi() {
    wifi_event_group = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "Menunggu koneksi Wi-Fi...");
    xEventGroupWaitBits(wifi_event_group, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
}

void init_mqtt() {
    esp_mqtt_client_config_t mqtt_cfg = {
        .broker.address.uri = MQTT_BROKER_URI,
    };
    mqtt_client = esp_mqtt_client_init(&mqtt_cfg);
    esp_mqtt_client_register_event(mqtt_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL);
    esp_mqtt_client_start(mqtt_client);
}

void send_telemetry(const char* id, const char* sector, uint32_t uptime, 
                    float volt, float current, float power, 
                    float lat, float lng, int alerts) {
    char json_payload[512];
    
    snprintf(json_payload, sizeof(json_payload), 
            "{\n"
            "    \"id\": \"%s\",\n"
            "    \"sector\": \"%s\",\n"
            "    \"uptime\": %d,\n"
            "    \"volt\": %.1f,\n"
            "    \"current\": %.2f,\n"
            "    \"power\": %.0f,\n"
            "    \"lat\": %f,\n"
            "    \"lng\": %f,\n"
            "    \"alerts\": %d\n"
            "}", 
            id, sector, uptime, volt, current, power, lat, lng, alerts);

    if (mqtt_client) {
        int msg_id = esp_mqtt_client_publish(mqtt_client, "iot/lights/L-107/telemetry", json_payload, 0, 1, 0);
        if (msg_id != -1) {
            ESP_LOGI(TAG, "Berhasil dikirim, msg_id=%d", msg_id);
        } 
        else {
            ESP_LOGE(TAG, "Gagal mengirim data MQTT");
        }
    }
}