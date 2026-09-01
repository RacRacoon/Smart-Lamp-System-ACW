"""
WebSocket manager - menggantikan node "websocket out" (Dashboard) + websocket-listener
("/ws/telemetry") yang dulu di Node-RED. Sekarang jadi endpoint WebSocket native di
FastAPI (satu proses/port yang sama dengan REST API), bukan server terpisah lagi.

MQTT client (paho-mqtt) jalan di thread terpisah dari event loop asyncio FastAPI,
jadi broadcast() dipanggil lewat run_coroutine_threadsafe agar aman lintas-thread.
"""
import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger("acw.ws")

_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


async def register(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.add(websocket)
    logger.info("Dashboard terhubung (%d client aktif)", len(_clients))


def unregister(websocket: WebSocket) -> None:
    _clients.discard(websocket)
    logger.info("Dashboard terputus (%d client aktif)", len(_clients))


_SEND_TIMEOUT_SECONDS = 5.0  # satu klien macet (WiFi jelek dkk) tidak boleh nahan
                              # broadcast ke klien lain nunggu tanpa batas


async def _send_one(client: WebSocket, message: str) -> None:
    try:
        await asyncio.wait_for(client.send_text(message), timeout=_SEND_TIMEOUT_SECONDS)
    except Exception:
        _clients.discard(client)


async def _broadcast_async(payload: dict) -> None:
    """Kirim ke SEMUA klien BERSAMAAN (asyncio.gather), bukan satu-satu berurutan -
    sebelumnya satu dashboard yang koneksinya lambat/macet menahan pengiriman ke
    dashboard lain nunggu giliran (loop for + await berurutan). Kegagalan satu klien
    (return_exceptions=True) tidak boleh membatalkan pengiriman ke klien lainnya."""
    if not _clients:
        return
    message = json.dumps(payload)
    await asyncio.gather(
        *(_send_one(client, message) for client in list(_clients)),
        return_exceptions=True,
    )


def broadcast(payload: dict) -> None:
    """Dipanggil dari thread MQTT (bukan dari dalam event loop FastAPI)."""
    if _loop is None:
        logger.warning("Event loop belum siap, payload dibuang: %s", payload)
        return
    asyncio.run_coroutine_threadsafe(_broadcast_async(payload), _loop)
