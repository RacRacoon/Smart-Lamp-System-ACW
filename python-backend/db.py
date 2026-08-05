"""
Akses PostgreSQL. Query di sini SENGAJA dibuat identik secara hasil dengan semua node
postgresql di node-red-flow-acw.json, supaya kontrak data ke frontend (Dashboard_Monitoring)
tidak berubah sama sekali saat migrasi.

Perbedaan yang disengaja dari versi Node-RED:
- insert_alert() dan semua query lain di sini memakai parameterized query. Versi Node-RED
  lama (Evaluasi & Build Query Alert) sempat menyusun SQL lewat string interpolation
  langsung untuk INSERT alert - itu rawan SQL injection dan tidak diikuti di sini.
"""
import logging
from typing import Any

import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

import config

logger = logging.getLogger("acw.db")

_pool: ThreadedConnectionPool | None = None


def init_pool(minconn: int = 1, maxconn: int = 10) -> None:
    global _pool
    _pool = ThreadedConnectionPool(
        minconn,
        maxconn,
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
    )
    logger.info("Pool koneksi PostgreSQL siap (%s:%s/%s)", config.DB_HOST, config.DB_PORT, config.DB_NAME)


def _run(query: str, params: tuple) -> None:
    """Eksekusi query tanpa hasil baris (INSERT/UPDATE/DELETE polos)."""
    if _pool is None:
        raise RuntimeError("Panggil init_pool() dulu sebelum query")
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def _fetch(query: str, params: tuple) -> list[dict[str, Any]]:
    """Eksekusi query yang mengembalikan baris (SELECT / ... RETURNING ...) sebagai list of dict."""
    if _pool is None:
        raise RuntimeError("Panggil init_pool() dulu sebelum query")
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        conn.commit()
        return [dict(r) for r in rows]
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def device_exists(device_id: str) -> bool:
    """Gerbang whitelist perangkat - lihat mqtt_ingest.py._handle_telemetry().
    Device harus diinput manual ke tabel devices lebih dulu (lewat psql/admin tool)
    sebelum telemetry dari device_id itu diterima. Tidak ada lagi auto-register."""
    rows = _fetch("SELECT 1 FROM devices WHERE device_id = %s;", (device_id,))
    return bool(rows)


def insert_telemetry(
    device_id: str,
    volt: float,
    current: float,
    power: float,
    uptime_hours: float,
    dim: int,
) -> None:
    """Setara dengan bagian INSERT telemetry_logs dari query CTE "Parse & Generate
    SQL Query" (ingest MQTT). Bagian auto-register device sudah dihapus - device_id
    dijamin sudah ada di tabel devices oleh device_exists() sebelum fungsi ini dipanggil."""
    query = """
        INSERT INTO telemetry_logs (device_id, volt, current, power, uptime, dim, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW());
    """
    _run(query, (device_id, volt, current, power, uptime_hours, dim))


def insert_alert(
    device_id: str,
    level: str,
    title: str,
    message: str,
    volt: float,
    current: float,
    power: float,
    threshold_info: str,
) -> None:
    """Setara dengan node "Save ALERT Only" (dari ingest MQTT), tapi parameterized."""
    query = """
        INSERT INTO alerts (device_id, level, title, message, volt, current, power, threshold_info, is_read, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, NOW());
    """
    params = (device_id, level, title, message, volt, current, power, threshold_info)
    _run(query, params)


def get_devices_latest() -> list[dict[str, Any]]:
    """Setara dengan node "Get from DB" (GET /api/devices-latest)."""
    query = """
        SELECT DISTINCT ON (d.device_id)
            d.device_id AS id,
            d.sector_name AS sector,
            d.latitude AS lat,
            d.longitude AS lng,
            d.max_lifespan AS max_lifespan,
            COALESCE(t.volt, 0) AS volt,
            COALESCE(t.current, 0) AS current,
            COALESCE(t.power, 0) AS power,
            COALESCE(t.uptime, 0) AS uptime,
            COALESCE(t.dim, 80) AS dim,
            t.created_at AS last_update
        FROM devices d
        LEFT JOIN telemetry_logs t ON d.device_id = t.device_id
        ORDER BY d.device_id, t.created_at DESC;
    """
    return _fetch(query, ())


def get_device_latest(device_id: str) -> dict[str, Any] | None:
    """Status & telemetry terbaru SATU lampu - dipakai analyze_device() (AI per-lampu
    di Riwayat Data) supaya gak perlu tarik data SEMUA lampu terus filter di Python."""
    query = """
        SELECT
            d.device_id AS id,
            d.sector_name AS sector,
            d.max_lifespan AS max_lifespan,
            COALESCE(t.volt, 0) AS volt,
            COALESCE(t.current, 0) AS current,
            COALESCE(t.power, 0) AS power,
            COALESCE(t.uptime, 0) AS uptime,
            COALESCE(t.dim, 80) AS dim,
            t.created_at AS last_update
        FROM devices d
        LEFT JOIN telemetry_logs t ON d.device_id = t.device_id
        WHERE d.device_id = %s
        ORDER BY t.created_at DESC
        LIMIT 1;
    """
    rows = _fetch(query, (device_id,))
    return rows[0] if rows else None


def get_telemetry_history(device_id: str) -> list[dict[str, Any]]:
    """Setara dengan node "Get Telemetry History" (GET /api/telemetry-history)."""
    query = """
        SELECT
            TO_CHAR(created_at, 'HH24:MI') as time_label,
            volt,
            current as ampere,
            power as watt
        FROM (
            SELECT created_at, volt, current, power
            FROM telemetry_logs
            WHERE device_id = %s
            ORDER BY created_at DESC
            LIMIT 100
        ) sub
        ORDER BY created_at ASC;
    """
    return _fetch(query, (device_id,))


def get_alerts_history(limit: int) -> list[dict[str, Any]]:
    """Setara dengan node "Get Alerts History DB" (GET /api/alerts-history)."""
    query = """
        SELECT
            id, device_id, level, title, message,
            volt, current, power, threshold_info, is_read, created_at
        FROM alerts
        ORDER BY created_at DESC
        LIMIT %s;
    """
    return _fetch(query, (limit,))


def mark_alert_read(alert_id: int) -> list[dict[str, Any]]:
    """Setara dengan node "Update Alert is_read" (PATCH /api/alerts/:id/read)."""
    query = "UPDATE alerts SET is_read = TRUE WHERE id = %s RETURNING id, is_read;"
    return _fetch(query, (alert_id,))


def mark_all_alerts_read() -> list[dict[str, Any]]:
    """Setara dengan node "Mark All Alerts Read" (POST /api/alerts/mark-all-read)."""
    query = "UPDATE alerts SET is_read = TRUE WHERE is_read = FALSE RETURNING id;"
    return _fetch(query, ())


def delete_alert(alert_id: int) -> list[dict[str, Any]]:
    """Setara dengan node "Delete One Alert" (DELETE /api/alerts/:id)."""
    query = "DELETE FROM alerts WHERE id = %s RETURNING id;"
    return _fetch(query, (alert_id,))


def delete_all_alerts() -> list[dict[str, Any]]:
    """Setara dengan node "Delete All Alerts" (DELETE /api/alerts)."""
    query = "DELETE FROM alerts RETURNING id;"
    return _fetch(query, ())


def get_sector_lamp_states() -> list[dict[str, Any]]:
    """Satu baris per lampu terdaftar: sektornya + uptime terbaru. Dipakai halaman
    Dashboard buat hitung jumlah lampu per sektor DAN klasifikasi kesehatannya.

    Sengaja balikin baris per lampu (bukan langsung COUNT per sektor di SQL): status
    kesehatan ditentukan alerts.classify_health(), satu-satunya sumber kebenaran
    ambang batasnya. Kalau di-agregat di SQL, ambang 8000/10000 jam itu harus
    ditulis ulang di query dan bisa lepas sinkron dengan config.py.

    LEFT JOIN sectors: sektor yang belum punya lampu tetap muncul (device_id NULL)
    supaya kelihatan di grafik pembagian, bukan hilang diam-diam."""
    query = """
        SELECT
            s.sector_name,
            d.device_id,
            COALESCE(t.uptime, 0) AS uptime
        FROM sectors s
        LEFT JOIN devices d ON d.sector_name = s.sector_name
        LEFT JOIN LATERAL (
            SELECT uptime FROM telemetry_logs
            WHERE device_id = d.device_id
            ORDER BY created_at DESC
            LIMIT 1
        ) t ON TRUE
        ORDER BY s.sector_name, d.device_id;
    """
    return _fetch(query, ())


def get_average_telemetry(buckets: int = 48) -> list[dict[str, Any]]:
    """Rata-rata telemetry SELURUH lampu, dikelompokkan per jam.

    Ambil N bucket terakhir yang PUNYA data, bukan jendela jam-dinding (mis.
    "24 jam terakhir"): kalau ingest MQTT sempat berhenti, filter jam-dinding
    balikin kosong walau riwayatnya ada. Pola LIMIT-lalu-urut-ulang-ASC ini sama
    dengan get_telemetry_history()."""
    query = """
        SELECT * FROM (
            SELECT
                TO_CHAR(date_trunc('hour', created_at), 'DD/MM HH24:MI') AS time_label,
                date_trunc('hour', created_at) AS bucket,
                ROUND(AVG(volt)::numeric, 2) AS avg_volt,
                ROUND(AVG(current)::numeric, 3) AS avg_current,
                ROUND(AVG(power)::numeric, 2) AS avg_power,
                COUNT(DISTINCT device_id) AS device_count
            FROM telemetry_logs
            GROUP BY bucket
            ORDER BY bucket DESC
            LIMIT %s
        ) sub
        ORDER BY bucket ASC;
    """
    rows = _fetch(query, (buckets,))
    for r in rows:
        r.pop("bucket", None)  # dipakai buat urut saja, tidak perlu dikirim ke frontend
    return rows


def get_alert_counts() -> dict[str, Any]:
    """Jumlah alert total & belum dibaca - kartu KPI di Dashboard."""
    rows = _fetch(
        "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_read = FALSE) AS unread FROM alerts;",
        (),
    )
    return rows[0] if rows else {"total": 0, "unread": 0}


def get_sector_schedules() -> list[dict[str, Any]]:
    """Semua fase jadwal RTC semua sektor, terurut per sektor lalu urutan operasional
    fase-nya. Tidak ada kolom urutan fase terpisah - urutan MEMANG ditentukan
    schedule_time, itu sebabnya UNIQUE(sector_name, schedule_time) di skema: dua fase
    gak boleh mulai di jam yang sama persis.

    BUKAN ORDER BY schedule_time polos: jadwal lampu jalan melintasi tengah malam
    (mulai sore, lanjut sampai dini hari) - kalau diurut jam-clock biasa dari 00:00,
    fase dini hari (mis. 03:30) akan muncul PALING AWAL karena nilainya paling kecil,
    padahal itu operasionalnya fase TERAKHIR. Trik di bawah: anggap "hari" jadwal
    lampu mulai jam 12 siang, bukan jam 00:00 - jadi jam >=12:00 (sore/malam) selalu
    di depan, jam <12:00 (dini hari) selalu di belakang."""
    query = """
        SELECT sector_name, TO_CHAR(schedule_time, 'HH24:MI') AS time, dim_level AS dim, cct_level AS cct
        FROM sector_schedules
        ORDER BY sector_name, (schedule_time < TIME '12:00') ASC, schedule_time ASC;
    """
    return _fetch(query, ())


def replace_sector_schedule(sector_name: str, phases: list[dict[str, Any]]) -> None:
    """Timpa seluruh fase jadwal milik satu sektor jadi persis daftar `phases` baru -
    hapus semua baris sektor ini lalu insert ulang, satu transaksi (bukan UPDATE per
    baris) karena jumlah fase admin bisa berubah (nambah/hapus fase, 3-6). FK
    sector_name -> sectors akan otomatis menolak (IntegrityError) kalau sektornya
    tidak terdaftar - lihat penanganannya di routes_schedules.py."""
    if _pool is None:
        raise RuntimeError("Panggil init_pool() dulu sebelum query")
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sector_schedules WHERE sector_name = %s;", (sector_name,))
            for phase in phases:
                cur.execute(
                    """
                    INSERT INTO sector_schedules (sector_name, schedule_time, dim_level, cct_level)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (sector_name, phase["time"], phase["dim"], phase["cct"]),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def get_device_ids_by_sector(sector_name: str) -> list[str]:
    """Daftar device_id fisik dalam satu sektor - dipakai buat push konfigurasi jadwal
    RTC ke tiap lampu lewat MQTT setelah jadwal sektornya disimpan."""
    rows = _fetch("SELECT device_id FROM devices WHERE sector_name = %s;", (sector_name,))
    return [r["device_id"] for r in rows]


def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Dipakai oleh /api/login. Tabel users dibuat manual (lihat migrasi sebelumnya)."""
    query = "SELECT username, password_hash, role FROM users WHERE username = %s;"
    rows = _fetch(query, (username,))
    return rows[0] if rows else None


def update_password_hash(username: str, new_hash: str) -> None:
    """Auto-upgrade hash lama (scrypt) ke argon2id setelah login berhasil. Lihat auth.py."""
    _run("UPDATE users SET password_hash = %s WHERE username = %s;", (new_hash, username))
