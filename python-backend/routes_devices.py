"""
Endpoint baca data perangkat & histori telemetry. Setara dengan:
- GET /api/devices-latest   (node "Get from DB")
- GET /api/telemetry-history (node "Get Telemetry History")
Kedua endpoint ini tidak butuh login (sama seperti perilaku Node-RED sebelumnya -
publik/read-only, beda dengan endpoint yang mengubah data seperti command & delete).
"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import config
import db
import rate_limit

logger = logging.getLogger("acw.routes.devices")
router = APIRouter(prefix="/api", tags=["devices"])


class DeviceLatest(BaseModel):
    id: str
    sector: str | None = None
    lat: float | None = None
    lng: float | None = None
    max_lifespan: int | None = None
    volt: float
    current: float
    power: float
    uptime: float
    dim: int
    last_update: datetime | None = None


class TelemetryPoint(BaseModel):
    time_label: str
    volt: float
    ampere: float
    watt: float


def _enforce_public_rate_limit(request: Request) -> None:
    allowed, retry_after = rate_limit.check(
        "public_read", rate_limit.client_ip(request),
        config.RATE_LIMIT_PUBLIC_MAX, config.RATE_LIMIT_PUBLIC_WINDOW,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": f"Terlalu banyak permintaan. Coba lagi dalam {retry_after} detik."},
        )


@router.get("/devices-latest", response_model=list[DeviceLatest])
def devices_latest(request: Request):
    _enforce_public_rate_limit(request)
    return db.get_devices_latest()


@router.get("/telemetry-history", response_model=list[TelemetryPoint])
def telemetry_history(request: Request, device_id: str = "L-101"):
    _enforce_public_rate_limit(request)
    return db.get_telemetry_history(device_id)
