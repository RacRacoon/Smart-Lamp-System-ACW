"""
Entrypoint. Jalanin: python main.py

Service ini menggantikan sebagian node-red-flow-acw.json:
- Sub Telemetry Semua Lampu, Parse & Generate SQL Query, Evaluasi & Build Query Alert,
  Save to PostgreSQL, Save ALERT Only, dan websocket-out "Dashboard".

Endpoint HTTP lain (GET /api/devices-latest, /api/telemetry-history, /api/alerts-history,
POST /api/lights/:id/command, POST /api/login, dll) TETAP dilayani Node-RED seperti biasa —
service ini cuma menulis ke tabel Postgres yang sama, jadi endpoint itu tidak perlu diubah.
"""
import asyncio
import logging

import db
import mqtt_ingest
import ws_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("acw.main")


async def main() -> None:
    db.init_pool()
    mqtt_ingest.start()  # jalan di thread background, non-blocking
    logger.info("Ingest MQTT+Postgres aktif, menunggu telemetry...")
    await ws_server.start()  # blocking, jalan selamanya di event loop utama


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Dihentikan oleh user.")
