"""
Konfigurasi service. Semua nilai bisa dioverride lewat environment variable,
default-nya disamakan persis dengan konfigurasi yang ada di node-red-flow-acw.json
supaya perilaku Postgres/MQTT tidak berubah saat migrasi.
"""
import os

# --- MQTT ---
# Broker publik yang sama dipakai oleh flow Node-RED lama (docker_mosquitto_broker).
MQTT_HOST = os.environ.get("MQTT_HOST", "broker.emqx.io")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TELEMETRY_TOPIC = os.environ.get("MQTT_TELEMETRY_TOPIC", "iot/lights/+/telemetry")
MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "acw_python_ingest")

# --- PostgreSQL ---
# Sama dengan node postgreSQLConfig "f7f72ff7bfaa5606" di node-red-flow-acw.json.
DB_HOST = os.environ.get("DB_HOST", "postgres_db")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "smart_lights")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "ACW123")

# --- Server HTTP+WebSocket (satu proses FastAPI, dipakai langsung oleh script.js) ---
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))

# --- Sesi login (disimpan di memori proses, sama seperti global context Node-RED dulu) ---
SESSION_DURATION_HOURS = int(os.environ.get("SESSION_DURATION_HOURS", "12"))

# --- MQTT command (kendali dim dari dashboard, publish ke ESP32) ---
MQTT_COMMAND_TOPIC_TEMPLATE = "iot/lights/{device_id}/command"

# --- CORS ---
CORS_ALLOW_ORIGINS = os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",")

# --- Nilai default kalau field tidak dikirim ESP32 (identik dengan fallback di flow lama) ---
DEFAULT_SECTOR = "Sektor 2 (Kertajaya - Depan ITS)"
DEFAULT_LAT = -7.279315
DEFAULT_LNG = 112.789253
DEFAULT_DIM = 80
DEFAULT_MAX_LIFESPAN = 10000

# --- Ambang batas health & alert (identik dengan Parse & Generate SQL Query + Evaluasi & Build Query Alert) ---
UPTIME_NEED_MAINTENANCE_HOURS = 10000
UPTIME_WARNING_HOURS = 8000

VOLT_SPIKE_THRESHOLD = 240
VOLT_OFFLINE_THRESHOLD = 200
CURRENT_SPIKE_THRESHOLD = 1.5
