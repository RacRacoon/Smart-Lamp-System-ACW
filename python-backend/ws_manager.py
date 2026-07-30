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


async def _broadcast_async(payload: dict) -> None:
    if not _clients:
        return
    message = json.dumps(payload)
    for client in list(_clients):
        try:
            await client.send_text(message)
        except Exception:
            _clients.discard(client)


def broadcast(payload: dict) -> None:
    """Dipanggil dari thread MQTT (bukan dari dalam event loop FastAPI)."""
    if _loop is None:
        logger.warning("Event loop belum siap, payload dibuang: %s", payload)
        return
    asyncio.run_coroutine_threadsafe(_broadcast_async(payload), _loop)
