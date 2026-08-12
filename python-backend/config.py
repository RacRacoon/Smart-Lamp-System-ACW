"""
Konfigurasi service. Semua nilai bisa dioverride lewat environment variable,
default-nya disamakan persis dengan konfigurasi yang ada di node-red-flow-acw.json
supaya perilaku Postgres/MQTT tidak berubah saat migrasi.
"""
import os
import re

# --- MQTT ---
# Broker publik yang sama dipakai oleh flow Node-RED lama (docker_mosquitto_broker).
MQTT_HOST = os.environ.get("MQTT_HOST", "broker.emqx.io")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TELEMETRY_TOPIC = os.environ.get("MQTT_TELEMETRY_TOPIC", "iot/lights/+/telemetry")
MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "acw_python_ingest")

# Charset device_id yang diterima. Broker default (broker.emqx.io) itu publik tanpa auth,
# jadi topic & payload telemetry bisa diisi siapa saja - device_id yang masuk lewat situ
# ikut tertulis ke pesan alert, tersimpan permanen di tabel alerts, lalu dirender ulang
# di dashboard. Batasi ke charset ID yang wajar di sini supaya markup/HTML tidak pernah
# masuk sistem sejak awal (dashboard tetap meng-escape saat render - dua lapis, karena
# baris alert lama yang terlanjur tersimpan sebelum aturan ini ada tidak ikut terbersihkan).
DEVICE_ID_PATTERN = os.environ.get("DEVICE_ID_PATTERN", r"^[A-Za-z0-9._-]{1,64}$")
_DEVICE_ID_RE = re.compile(DEVICE_ID_PATTERN)


def is_valid_device_id(device_id: str) -> bool:
    """Gerbang BENTUK device_id - beda tujuan dari whitelist db.device_exists() yang
    menjawab "ID ini terdaftar?". Perlu dua-duanya: ID yang ditolak whitelist pun tetap
    ikut ditulis ke pesan alert dan dirender di dashboard, jadi bentuknya harus sudah
    aman lebih dulu. Dipakai di dua pintu masuk device_id: ingest MQTT (mqtt_ingest.py)
    dan form onboarding admin (routes_provisioning.py)."""
    return bool(device_id) and bool(_DEVICE_ID_RE.match(device_id))

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

# --- Pool koneksi Postgres ---
# Default lama (maxconn=10) kebukti kehabisan di bawah beban wajar: uji beban pentest
# (12 Agu 2026) - 50 request bersamaan ke satu endpoint publik bikin 86% gagal
# "connection pool exhausted". Satu proses uvicorn lewat FastAPI run_in_threadpool bisa
# sampai puluhan thread jalan bersamaan buat endpoint sync (default anyio ~40), jadi
# pool 10 gampang telak. Postgres sendiri max_connections default 100 - 25 masih longgar
# (sisa headroom buat psql debug manual dkk, lihat komentar port 5432 di docker-compose).
DB_POOL_MINCONN = int(os.environ.get("DB_POOL_MINCONN", "2"))
DB_POOL_MAXCONN = int(os.environ.get("DB_POOL_MAXCONN", "25"))

# --- MQTT command (kendali dim dari dashboard, publish ke ESP32) ---
MQTT_COMMAND_TOPIC_TEMPLATE = "iot/lights/{device_id}/command"

# --- CORS ---
CORS_ALLOW_ORIGINS = os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",")

# --- Rate limit (lihat rate_limit.py) ---
# Login: cukup longgar buat orang yang salah ketik beberapa kali, cukup ketat buat
# bikin tebak-tebakan password jadi tidak praktis.
RATE_LIMIT_LOGIN_MAX = int(os.environ.get("RATE_LIMIT_LOGIN_MAX", "10"))
RATE_LIMIT_LOGIN_WINDOW = int(os.environ.get("RATE_LIMIT_LOGIN_WINDOW", "300"))

# Chat/analisis AI: tiap panggilan menembak kuota Gemini tier gratis yang ketat, jadi
# batasnya soal ongkos, bukan soal keamanan.
RATE_LIMIT_AI_MAX = int(os.environ.get("RATE_LIMIT_AI_MAX", "20"))
RATE_LIMIT_AI_WINDOW = int(os.environ.get("RATE_LIMIT_AI_WINDOW", "60"))

# Aksi admin yang sudah lolos token (command dim, provisioning, jadwal, hapus alert) -
# perlu token valid buat sampai sini, tapi token bocor/dipakai bareng-bareng masih bisa
# nyepam MQTT ke hardware fisik atau nulis DB tanpa henti tanpa ini. Lebih longgar dari
# limit publik karena ini kerja NORMAL seorang admin (bukan permintaan baca pasif),
# kuncinya token sesi itu sendiri - bukan IP, supaya kantor sekantor pakai IP sama tidak
# saling mentok jatah.
RATE_LIMIT_ADMIN_WRITE_MAX = int(os.environ.get("RATE_LIMIT_ADMIN_WRITE_MAX", "30"))
RATE_LIMIT_ADMIN_WRITE_WINDOW = int(os.environ.get("RATE_LIMIT_ADMIN_WRITE_WINDOW", "10"))

# Endpoint AI tool-calling (get_alerts_history) pakai batas atas yang sama dengan
# GET /api/alerts-history (routes_alerts.py) - dua-duanya jalan ke query yang sama,
# jadi harus dua-duanya dijaga, bukan cuma jalur HTTP-nya.
MAX_ALERTS_LIMIT = 500

# Endpoint baca publik (devices-latest, telemetry-history, system-overview,
# alerts-history, mark-read) tidak butuh login by design, tapi tanpa batas ini bisa
# dipukul berkali-kali per detik oleh siapa saja - tiap panggilan tetap query Postgres
# (pool cuma 10 koneksi), jadi tanpa limit ini jalan DoS murah ke dashboard buat semua
# pengguna sah. Lebih longgar dari limit login/AI karena ini bukan soal ongkos/tebak
# password, cuma jaga supaya satu klien tidak menghabiskan pool koneksi sendirian.
RATE_LIMIT_PUBLIC_MAX = int(os.environ.get("RATE_LIMIT_PUBLIC_MAX", "60"))
RATE_LIMIT_PUBLIC_WINDOW = int(os.environ.get("RATE_LIMIT_PUBLIC_WINDOW", "10"))

# Default False: backend yang diakses langsung (tanpa Caddy di depan) TIDAK boleh
# percaya X-Forwarded-For - header itu dikirim klien dan bisa dipalsukan buat lolos
# rate limit. Set "true" HANYA kalau proses ini memang di belakang reverse proxy
# (lihat Caddyfile) yang menimpa/menambahkan header itu sendiri.
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "false").lower() == "true"

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

# --- Asisten AI (chat dasbor, jawaban di-ground ke data live lewat tool-calling) ---
# Lewat endpoint OpenAI-compatible resmi Gemini (bukan OpenRouter lagi). Untuk API
# key baru per Agustus 2026, model "flash" reguler ("gemini-2.5-flash",
# "gemini-2.0-flash", alias "gemini-flash-latest" -> gemini-3.6-flash) sudah
# ditutup/dibatasi sangat ketat (quota free tier limit 0-5 req) buat proyek baru -
# cuma varian "lite" yang masih dapat kuota gratis normal, makanya dipakai
# "gemini-flash-lite-latest". Key jangan pernah di-hardcode di sini, selalu dari
# env var (lihat .env di folder docker-compose, sengaja tidak ikut repo git).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
