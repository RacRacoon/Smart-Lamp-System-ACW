"""
Akses PostgreSQL. Query di sini SENGAJA dibuat identik secara hasil dengan
node-red-flow-acw.json ("Parse & Generate SQL Query" dan "Evaluasi & Build Query Alert"),
supaya endpoint HTTP lain di Node-RED (GET /api/devices-latest, /api/telemetry-history,
/api/alerts-history) yang masih membaca tabel yang sama tetap jalan tanpa perubahan.

Perbedaan yang disengaja dari versi Node-RED:
- insert_alert() memakai parameterized query. Versi Node-RED lama menyusun SQL
  lewat string interpolation langsung (rawan SQL injection), itu tidak diikuti di sini.
"""
import logging
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
    """Setara dengan query CTE di node 172245d468e0a128 (Parse & Generate SQL Query)."""
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
    """Setara dengan node ae807cdc6832aa7f (Save ALERT Only), tapi parameterized."""
    query = """
        INSERT INTO alerts (device_id, level, title, message, volt, current, power, threshold_info, is_read, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, NOW());
    """
    params = (device_id, level, title, message, volt, current, power, threshold_info)
    _run(query, params)
