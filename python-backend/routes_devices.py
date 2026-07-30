"""
Endpoint baca data perangkat & histori telemetry. Setara dengan:
- GET /api/devices-latest   (node "Get from DB")
- GET /api/telemetry-history (node "Get Telemetry History")
Kedua endpoint ini tidak butuh login (sama seperti perilaku Node-RED sebelumnya -
publik/read-only, beda dengan endpoint yang mengubah data seperti command & delete).
"""
import logging

from fastapi import APIRouter

import db

logger = logging.getLogger("acw.routes.devices")
router = APIRouter(prefix="/api", tags=["devices"])


@router.get("/devices-latest")
def devices_latest():
    return db.get_devices_latest()


@router.get("/telemetry-history")
def telemetry_history(device_id: str = "L-101"):
    return db.get_telemetry_history(device_id)
