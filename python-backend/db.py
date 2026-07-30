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


def upsert_device_and_insert_telemetry(
    device_id: str,
    sector: str,
    lat: float,
    lng: float,
    volt: float,
    current: float,
    power: float,
    uptime_hours: float,
    dim: int,
) -> None:
    """Setara dengan query CTE "Parse & Generate SQL Query" (ingest MQTT)."""
    query = """
        WITH auto_register_device AS (
            INSERT INTO devices (device_id, sector_name, latitude, longitude, max_lifespan)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (device_id) DO NOTHING
        )
        INSERT INTO telemetry_logs (device_id, volt, current, power, uptime, dim, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW());
    """
    params = (
        device_id, sector, lat, lng, config.DEFAULT_MAX_LIFESPAN,
        device_id, volt, current, power, uptime_hours, dim,
    )
    _run(query, params)


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


def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Dipakai oleh /api/login. Tabel users dibuat manual (lihat migrasi sebelumnya)."""
    query = "SELECT username, password_hash, role FROM users WHERE username = %s;"
    rows = _fetch(query, (username,))
    return rows[0] if rows else None
