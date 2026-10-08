-- Index tambahan di luar constraint bawaan (PK/FK/UNIQUE) - skema tabel sendiri
-- dibuat manual lewat migrasi terpisah (lihat komentar di db.py), TIDAK ada di repo
-- ini. File ini cuma nyatet index performa supaya bisa dipasang ulang kalau
-- database pernah dibikin dari nol lagi.
--
-- Jalankan manual: psql -U admin -d smart_lights -f schema_indexes.sql

-- telemetry_logs cuma punya index di primary key (id). Semua query utama
-- (get_telemetry_history, get_devices_latest, get_average_telemetry, dst di db.py)
-- filter/urut lewat (device_id, created_at) - tanpa index ini, query itu full-scan
-- seluruh tabel. Tidak kerasa waktu baris masih ribuan, tapi begitu banyak lampu PJU
-- asli kirim telemetry terus-terusan, tabel ini tumbuh cepat dan query jadi lambat.
CREATE INDEX IF NOT EXISTS idx_telemetry_logs_device_created
ON telemetry_logs (device_id, created_at DESC);

-- alerts cuma punya index di primary key (id). get_alerts_history() (GET
-- /api/alerts-history, publik, endpoint paling sering dipukul - lihat rate_limit.py)
-- query "ORDER BY created_at DESC LIMIT %s" tanpa index ini - full table scan + sort
-- SETIAP panggilan. Query lambat = koneksi pool ditahan lebih lama = pool 25 (lihat
-- config.DB_POOL_MAXCONN) lebih gampang penuh lagi di beban tinggi. Ditemukan lewat
-- audit langsung ke skema live (\d alerts), bukan cuma baca kode - schema_indexes.sql
-- sendiri sempat kelewat nambahin index ini sejak awal.
CREATE INDEX IF NOT EXISTS idx_alerts_created_at
ON alerts (created_at DESC);

-- Usia pakai lampu yang menetap. Database yang dibuat sebelum kolom ini ada
-- (schema.sql versi lama) tetap bisa dipakai setelah menjalankan berkas ini:
-- tanpa kedua kolom itu, ingest MQTT akan menolak menghitung usia lampu dan
-- angkanya berhenti di nol.
ALTER TABLE devices ADD COLUMN IF NOT EXISTS lamp_hours DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS lamp_seen  TIMESTAMP;
