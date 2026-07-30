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
import mqtt_ingest

logger = logging.getLogger("acw.routes.command")
router = APIRouter(prefix="/api", tags=["command"])


class DimCommand(BaseModel):
    dim: int = 0


@router.post("/lights/{device_id}/command")
def send_command(
    device_id: str,
    body: DimCommand,
    x_acw_token: str | None = Header(default=None, alias="X-ACW-Token"),
):
    if body.dim < 0 or body.dim > 100:
        raise HTTPException(status_code=400, detail={"error": "Invalid id or dim (0-100)"})

    if not auth.is_admin(x_acw_token):
        raise HTTPException(status_code=403, detail={"error": "Forbidden: hanya admin yang bisa mengubah kecerahan"})

    mqtt_ingest.publish_dim_command(device_id, body.dim)
    return {"id": device_id, "dim": body.dim}
