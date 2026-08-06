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
