"""
WebSocket server buat dashboard (Dashboard_Monitoring/script.js connect ke sini).
Menggantikan node "websocket out" (406c6023626f91d0) + websocket-listener
("/ws/telemetry") yang sebelumnya ada di Node-RED untuk topik ini.

MQTT client (paho-mqtt) jalan di thread terpisah dari event loop asyncio ini,
jadi broadcast() dipanggil lewat run_coroutine_threadsafe agar aman lintas-thread.
"""
import asyncio
import json
import logging

import websockets

import config

logger = logging.getLogger("acw.ws")

_clients = set()  # koneksi WebSocket dashboard yang sedang aktif
_loop: asyncio.AbstractEventLoop | None = None


async def _handler(websocket):
    _clients.add(websocket)
    logger.info("Dashboard terhubung (%d client aktif)", len(_clients))
    try:
        async for _ in websocket:
            pass  # dashboard cuma menerima, tidak mengirim pesan lewat koneksi ini
    finally:
        _clients.discard(websocket)
        logger.info("Dashboard terputus (%d client aktif)", len(_clients))


async def _broadcast_async(payload: dict) -> None:
    if not _clients:
        return
    message = json.dumps(payload)
    # kirim ke semua client, abaikan yang gagal (misal baru saja disconnect)
    await asyncio.gather(
        *(client.send(message) for client in list(_clients)),
        return_exceptions=True,
    )


def broadcast(payload: dict) -> None:
    """Dipanggil dari thread MQTT (bukan dari dalam event loop)."""
    if _loop is None:
        logger.warning("WS server belum siap, payload dibuang: %s", payload)
        return
    asyncio.run_coroutine_threadsafe(_broadcast_async(payload), _loop)


async def start() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    async with websockets.serve(_handler, config.WS_HOST, config.WS_PORT):
        logger.info("WebSocket server siap di ws://%s:%s", config.WS_HOST, config.WS_PORT)
        await asyncio.Future()  # jalan selamanya
