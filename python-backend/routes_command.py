"""
POST /api/lights/{device_id}/command - kendali cepat (dim) dari dashboard.
Setara dengan node "Parse Command & Build MQTT" + "Publish to MQTT" di
node-red-flow-acw.json, termasuk perbaikan bug lama:
- endpoint yang benar (dulu sempat salah alamat di frontend, sudah dibetulkan)
- response HTTP selalu terkirim (dulu ada varian yang bikin request nge-hang)
- admin-only lewat token sesi (bukan cuma disembunyikan di UI)
"""
import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

import auth
import config
import mqtt_ingest
import rate_limit

logger = logging.getLogger("acw.routes.command")
router = APIRouter(prefix="/api", tags=["command"])


class DimCommand(BaseModel):
    # Keduanya opsional, dan minimal satu harus ada. Dulu dim bernilai bawaan 0,
    # jadi perintah yang hanya ingin mengubah mode otomatis akan ikut mengirim
    # "dim: 0" dan memadamkan lampu tanpa diminta.
    dim: int | None = None
    auto: bool | None = None


class CommandResponse(BaseModel):
    id: str
    dim: int | None = None
    auto: bool | None = None


def _enforce_admin_write_rate_limit(x_acw_token: str | None) -> None:
    allowed, retry_after = rate_limit.check(
        "admin_write", x_acw_token,
        config.RATE_LIMIT_ADMIN_WRITE_MAX, config.RATE_LIMIT_ADMIN_WRITE_WINDOW,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": f"Terlalu banyak permintaan. Coba lagi dalam {retry_after} detik."},
        )


@router.post("/lights/{device_id}/command", response_model=CommandResponse)
def send_command(
    device_id: str,
    body: DimCommand,
    x_acw_token: str | None = Header(default=None, alias="X-ACW-Token"),
):
    if body.dim is None and body.auto is None:
        raise HTTPException(
            status_code=400,
            detail={"error": "Perintah kosong: sertakan 'dim' (0-100) dan/atau 'auto' (true/false)"},
        )

    if body.dim is not None and (body.dim < 0 or body.dim > 100):
        raise HTTPException(status_code=400, detail={"error": "Invalid id or dim (0-100)"})

    if not auth.is_admin(x_acw_token):
        raise HTTPException(status_code=403, detail={"error": "Forbidden: hanya admin yang bisa mengubah kecerahan"})

    _enforce_admin_write_rate_limit(x_acw_token)

    # device_id ikut dirakit jadi topic MQTT mentah-mentah (mqtt_ingest.py) - broker
    # publik (broker.emqx.io) tanpa auth/namespace, jadi ID berisi "/" bisa mengubah
    # topic tujuan publish di luar "iot/lights/X/command" yang dimaksud. Dicek di sini
    # dulu biar admin dapat pesan error yang jelas (mqtt_ingest.py sendiri juga menolak
    # sebagai jaring kedua).
    if not config.is_valid_device_id(device_id):
        raise HTTPException(
            status_code=400,
            detail={"error": "ID lampu tidak valid (hanya huruf, angka, titik, garis bawah, tanda hubung)"},
        )

    payload: dict = {}
    if body.dim is not None:
        payload["dim"] = body.dim
    if body.auto is not None:
        payload["auto"] = body.auto

    mqtt_ingest.publish_control_command(device_id, payload)
    return {"id": device_id, "dim": body.dim, "auto": body.auto}
