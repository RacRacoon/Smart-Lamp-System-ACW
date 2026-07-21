#include "telemetry.h"
#include "esp_log.h"


/*
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
*/


extern SemaphoreHandle_t uart1_mutex;

static const char *TAG = "CELLULAR_MQTT";
#define MODEM_UART_NUM UART_NUM_1 // Harus sama dengan UART yang dipakai GPS

// Fungsi internal (Helper) untuk mengirim AT Command dan menunggu sejenak
static void send_at_command(const char* cmd, int delay_ms) {
    uart_write_bytes(MODEM_UART_NUM, cmd, strlen(cmd));
    vTaskDelay(pdMS_TO_TICKS(delay_ms));
}

void init_cellular_mqtt(void) {
    ESP_LOGI(TAG, "Menghidupkan layanan MQTT pada Modem...");

    // 1. Mulai layanan MQTT di modem
    send_at_command("AT+CMQTTSTART\r\n", 2000);

    // 2. Buat client MQTT baru (Client Index 0, ID: ESP32_StreetLight)
    send_at_command("AT+CMQTTACCQ=0,\"ESP32_StreetLight\"\r\n", 1000);

    // 3. Sambungkan ke Broker (Format: AT+CMQTTCONNECT=0,"URL",60,1)
    char connect_cmd[128];
    snprintf(connect_cmd, sizeof(connect_cmd), "AT+CMQTTCONNECT=0,\"%s\",60,1\r\n", MQTT_BROKER_URL);
    send_at_command(connect_cmd, 5000); // Tunggu 5 detik agar koneksi internet stabil
    
    ESP_LOGI(TAG, "Koneksi MQTT Seluler Selesai Dieksekusi.");
}

void send_telemetry_cellular(const char* id, const char* sector, uint32_t uptime, float volt, float current, float power, float lat, float lng, int alerts) {
    if(xSemaphoreTake(uart1_mutex,pdMS_TO_TICKS(1000))){
        char json_payload[512];
        snprintf(json_payload, sizeof(json_payload), 
                "{\"id\":\"%s\",\"sector\":\"%s\",\"uptime\":%lu,\"volt\":%.1f,\"current\":%.2f,\"power\":%.0f,\"lat\":%f,\"lng\":%f,\"alerts\":%d}", 
                id, sector, uptime, volt, current, power, lat, lng, alerts);

        int payload_len = strlen(json_payload);
        int topic_len = strlen(MQTT_TOPIC_PUB);
        char at_cmd[256];

        ESP_LOGI(TAG, "Mempersiapkan pengiriman Payload...");

        // 1. Set Topik (AT+CMQTTTOPIC=0,<panjang_topik>)
        snprintf(at_cmd, sizeof(at_cmd), "AT+CMQTTTOPIC=0,%d\r\n", topic_len);
        send_at_command(at_cmd, 500);
        send_at_command(MQTT_TOPIC_PUB, 500); // Kirim teks topiknya

        // 2. Set Payload (AT+CMQTTPAYLOAD=0,<panjang_payload>)
        snprintf(at_cmd, sizeof(at_cmd), "AT+CMQTTPAYLOAD=0,%d\r\n", payload_len);
        send_at_command(at_cmd, 500);
        send_at_command(json_payload, 500); // Kirim teks JSON-nya

        // 3. Publish (AT+CMQTTPUB=0,1,60) -> Index 0, QoS 1, Timeout 60s
        send_at_command("AT+CMQTTPUB=0,1,60\r\n", 2000);

        ESP_LOGI(TAG, "Data berhasil dilempar ke menara seluler!");

        char response[64];
        int len = uart_read_bytes(MODEM_UART_NUM, response, sizeof(response), pdMS_TO_TICKS(1000));
        if (len > 0) {
            response[len] = '\0';
            ESP_LOGI(TAG, "Modem replied: %s", response);
        }
        xSemaphoreGive(uart1_mutex);
    }
    else{
        ESP_LOGW(TAG, "Jalur komunikasi uart1 sibuk");
    }
}