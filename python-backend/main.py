"""
Entrypoint tunggal. Jalanin: uvicorn main:app --host 0.0.0.0 --port 8000

Satu proses ini menggantikan SELURUH node-red-flow-acw.json:
- REST API (devices, telemetry, alerts, login, command)
- WebSocket dashboard (/ws/telemetry)
- Ingest MQTT + tulis Postgres + evaluasi alert
- Publish MQTT command (kendali dim)

Dokumentasi API otomatis: http://localhost:8000/docs (Swagger UI dari FastAPI).
"""
import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
import db
import mqtt_ingest
import routes_alerts
import routes_auth
import routes_chat
import routes_command
import routes_devices
import routes_overview
import routes_schedules
import ws_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("acw.main")

app = FastAPI(title="ACW Smart Lighting API", version="1.0.0")

# CORS: menggantikan node "Set CORS & Headers" yang tadinya ditempel manual di
# setiap endpoint Node-RED + httpNodeCors yang sempat nonaktif di settings.js
# (itu penyebab login sempat "stuck" sebelum migrasi ini). Di sini cukup sekali,
# berlaku otomatis untuk semua endpoint termasuk preflight OPTIONS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    # Jaga bentuk response tetap flat {"error": "..."} seperti endpoint Node-RED dulu,
    # bukan bentuk default FastAPI {"detail": ...}.
    content = exc.detail if isinstance(exc.detail, dict) else {"error": exc.detail}
    return JSONResponse(status_code=exc.status_code, content=content)


app.include_router(routes_devices.router)
app.include_router(routes_alerts.router)
app.include_router(routes_auth.router)
app.include_router(routes_command.router)
app.include_router(routes_chat.router)
app.include_router(routes_schedules.router)
app.include_router(routes_overview.router)


@app.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket):
    await ws_manager.register(websocket)
    try:
        while True:
            await websocket.receive_text()  # dashboard cuma menerima, loop ini cuma buat deteksi disconnect
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.unregister(websocket)


@app.on_event("startup")
def on_startup():
    db.init_pool()
    ws_manager.set_loop(asyncio.get_event_loop())
    mqtt_ingest.start()  # jalan di thread background (paho-mqtt loop_start), non-blocking
    logger.info("ACW backend siap - REST, WebSocket, dan ingest MQTT aktif.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)
