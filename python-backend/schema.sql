-- ============================================================================
-- Skema database ACW Smart Lighting (PostgreSQL 15).
--
-- SUMBER KEBENARAN struktur tabel - sebelum file ini dibuat (13 Agu 2026), skema
-- tabel TIDAK ADA di repo sama sekali, cuma hidup di database yang kebetulan sedang
-- jalan (lihat SCHEMA_README.md buat cerita lengkapnya dan cara pakai file ini).
--
-- Asal: `pg_dump --schema-only` terhadap database `smart_lights` yang jalan di
-- postgres_db (Docker), lalu DIRAPIKAN MANUAL - urutan tabel ikut alur
-- ketergantungan data (bukan alfabetis seperti keluaran pg_dump mentah), komentar
-- ditambahkan tiap tabel/kolom yang tidak jelas dari namanya saja. Isinya tetap
-- 100% funsional sama dengan database live per tanggal dump - bukan skema yang
-- diinginkan/direncanakan, tapi skema yang BENERAN ADA sekarang.
--
-- Tidak ada tool migrasi (Alembic dkk) di proyek ini. Kalau nanti skema tabel
-- diubah manual (ALTER TABLE langsung di database), file ini WAJIB diperbarui
-- juga di commit yang sama - lihat SCHEMA_README.md bagian "Menjaga file ini
-- tetap akurat".
-- ============================================================================


-- ============================================================================
--  users - akun login dashboard
-- ============================================================================
-- Dua peran: 'admin' (akses penuh) dan 'user' (baca-saja/petugas monitoring) -
-- lihat python-backend/auth.py & routes_auth.py.
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50) NOT NULL,
    password_hash TEXT NOT NULL,   -- argon2id (auth.hash_password); hash scrypt lama
                                    -- (format Node crypto.scryptSync, "salt_hex:hash_hex")
                                    -- masih bisa diverifikasi juga - auto-upgrade ke
                                    -- argon2id diam-diam saat login berhasil, lihat
                                    -- auth.is_legacy_hash() / routes_auth.py
    role          VARCHAR(20) NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT users_username_key UNIQUE (username),
    CONSTRAINT users_role_check CHECK (role IN ('admin', 'user'))
);


-- ============================================================================
--  sectors - area geografis penerangan (mis. "Sektor 1 (Jalan Tunjungan)")
-- ============================================================================
-- Nama sektor JADI primary key (bukan id numerik terpisah) - dipilih apa adanya
-- dari nama jalan sungguhan di form onboarding admin (routes_provisioning.py),
-- sengaja TIDAK dibatasi charset seperti device_id karena isinya boleh pakai
-- spasi/kurung/tanda hubung.
CREATE TABLE sectors (
    sector_name VARCHAR(100) PRIMARY KEY,
    ldr_mode    BOOLEAN DEFAULT false,   -- true = kecerahan sektor ini ikut sensor
                                          -- cahaya (LDR) fisik, bukan jadwal RTC
                                          -- terjadwal di sector_schedules
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================================
--  devices - satu baris per tiang lampu PJU terdaftar
-- ============================================================================
CREATE TABLE devices (
    device_id    VARCHAR(50) PRIMARY KEY,   -- charset dibatasi [A-Za-z0-9._-]{1,64}
                                             -- di LAPISAN APLIKASI saja
                                             -- (config.is_valid_device_id) - TIDAK
                                             -- di-enforce lewat CHECK constraint di
                                             -- sini, jadi baris lama yang masuk
                                             -- sebelum aturan itu ada bisa saja
                                             -- masih longgar
    sector_name  VARCHAR(100) REFERENCES sectors(sector_name) ON DELETE SET NULL,
                                             -- sektor dihapus -> lampu jadi "tanpa
                                             -- sektor", BUKAN ikut terhapus - admin
                                             -- harus pindahkan/hapus lampunya sendiri
                                             -- lebih dulu (lihat pesan error di
                                             -- routes_provisioning.delete_sector())
    latitude     DOUBLE PRECISION,
    longitude    DOUBLE PRECISION,
    max_lifespan INTEGER DEFAULT 10000,     -- jam pakai sebelum status "Need
                                             -- Maintenance" (lihat
                                             -- config.UPTIME_NEED_MAINTENANCE_HOURS
                                             -- & alerts.classify_health())
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================================
--  alerts - riwayat peringatan (lonjakan tegangan/arus, offline, device asing)
-- ============================================================================
CREATE TABLE alerts (
    id             SERIAL PRIMARY KEY,
    device_id      VARCHAR(50) REFERENCES devices(device_id) ON DELETE CASCADE,
                                             -- lampu dihapus -> riwayat alert-nya
                                             -- IKUT terhapus (beda dari devices yang
                                             -- SET NULL kalau sektornya yang dihapus)
    level          VARCHAR(20) NOT NULL,    -- "Critical" - satu-satunya level yang
                                             -- dipakai saat ini, lihat alerts.py
    title          VARCHAR(100) NOT NULL,
    message        TEXT NOT NULL,           -- device_id ikut ditulis mentah ke sini
                                             -- kalau alert-nya soal device asing -
                                             -- WAJIB di-escapeHtml()/escapeJsString()
                                             -- saat dirender (lihat script.js,
                                             -- commit 01e8a3b - ini bekas jalur XSS
                                             -- tersimpan)
    volt           NUMERIC(5,2),
    current        NUMERIC(5,3),
    power          NUMERIC(6,2),
    threshold_info VARCHAR(100),
    is_read        BOOLEAN DEFAULT false,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_alerts_created_at ON alerts (created_at DESC);
-- ^ GET /api/alerts-history ORDER BY created_at DESC - endpoint publik paling
-- sering dipukul (lihat rate_limit.py bucket "public_read"). Ditambahkan
-- 13 Agu 2026 - sebelumnya full table scan + sort tiap panggilan, ikut mempercepat
-- pool koneksi Postgres penuh di beban tinggi (lihat config.DB_POOL_MAXCONN).


-- ============================================================================
--  telemetry_logs - histori pembacaan sensor tiap lampu (tegangan/arus/daya/uptime)
-- ============================================================================
-- Tabel yang TUMBUH TERCEPAT di seluruh skema - satu baris per pembacaan MQTT
-- tiap lampu (mqtt_ingest.py). Belum ada kebijakan retensi/arsip - lihat
-- SCHEMA_README.md bagian "Yang belum diselesaikan file ini".
CREATE TABLE telemetry_logs (
    id         BIGSERIAL PRIMARY KEY,   -- BIGINT sengaja (bukan SERIAL biasa) -
                                         -- volume baris paling besar di skema ini,
                                         -- INTEGER (max ~2.1 miliar) realistis kena
                                         -- limit lebih dulu dibanding tabel lain
    device_id  VARCHAR(50) REFERENCES devices(device_id) ON DELETE CASCADE,
    volt       NUMERIC(5,2),
    current    NUMERIC(5,3),
    power      NUMERIC(6,2),
    uptime     NUMERIC(10,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dim        INTEGER DEFAULT 8       -- level kecerahan (skala 1-10) SAAT pembacaan
                                        -- ini diambil - bukan level kecerahan terkini
);

CREATE INDEX idx_telemetry_logs_device_created
ON telemetry_logs (device_id, created_at DESC);
-- ^ WAJIB, bukan sekadar optimisasi - get_telemetry_history/get_devices_latest/
-- get_average_telemetry (db.py) semua filter+urut lewat (device_id, created_at).
-- Tanpa index ini, full-scan seluruh tabel di tabel yang paling cepat tumbuh.


-- ============================================================================
--  sector_schedules - jadwal kecerahan & kehangatan warna RTC per sektor
-- ============================================================================
-- 3-6 fase per sektor (MIN_PHASES/MAX_PHASES di routes_schedules.py). Firmware
-- ESP32 (modul RTC DS3231) yang mengeksekusi tiap fase mandiri sesuai jamnya
-- sendiri - backend TIDAK nge-trigger dim tiap jam dari sini, cuma push
-- konfigurasinya lewat MQTT retained message saat admin menyimpan.
CREATE TABLE sector_schedules (
    id            SERIAL PRIMARY KEY,
    sector_name   VARCHAR(100) REFERENCES sectors(sector_name) ON DELETE CASCADE,
                                            -- sektor dihapus -> jadwalnya IKUT
                                            -- terhapus (beda dari devices yang
                                            -- SET NULL - jadwal sektor kosong tidak
                                            -- ada gunanya disimpan sendirian)
    schedule_time TIME NOT NULL,
    dim_level     INTEGER NOT NULL,        -- 1-10, divalidasi Field(ge=1, le=10)
                                            -- di routes_schedules.py, TIDAK ada
                                            -- CHECK constraint setara di DB
    cct_level     INTEGER NOT NULL,        -- 0-100 (color temperature/kehangatan
                                            -- warna), divalidasi Field(ge=0, le=100)
                                            -- di routes_schedules.py, TIDAK ada
                                            -- CHECK constraint setara di DB

    CONSTRAINT sector_schedules_sector_name_schedule_time_key
        UNIQUE (sector_name, schedule_time)
    -- ^ dua fase tidak boleh mulai di jam yang sama - urutan eksekusi fase MEMANG
    -- ditentukan schedule_time-nya sendiri, tidak ada kolom urutan terpisah
    -- (lihat db.get_sector_schedules(), ORDER BY sector_name, schedule_time)
);
