"""
Endpoint Kotak Peringatan. Setara dengan node-node alert di node-red-flow-acw.json:
- GET   /api/alerts-history          (baca, publik - siapa saja boleh lihat)
- PATCH /api/alerts/:id/read         (tandai dibaca - publik, admin & user boleh)
- POST  /api/alerts/mark-all-read    (tandai semua dibaca - publik, admin & user boleh)
- DELETE /api/alerts/:id             (hapus satu - ADMIN ONLY)
- DELETE /api/alerts                 (hapus semua - ADMIN ONLY)

Aturan admin-only ini menegaskan ulang perbaikan "user cuma boleh tandai dibaca,
tidak boleh hapus" yang sebelumnya dipasang di Node-RED - sekarang jadi bagian
permanen dari API, bukan tempelan.
"""
import logging

from fastapi import APIRouter, Header, HTTPException

import auth
import db

logger = logging.getLogger("acw.routes.alerts")
router = APIRouter(prefix="/api", tags=["alerts"])


def _require_admin(x_acw_token: str | None) -> None:
    if not auth.is_admin(x_acw_token):
        raise HTTPException(status_code=403, detail={"error": "Forbidden: hanya admin yang bisa menghapus alert"})


@router.get("/alerts-history")
def alerts_history(limit: int = 50):
    return db.get_alerts_history(limit)


@router.patch("/alerts/{alert_id}/read")
def alert_mark_read(alert_id: int):
    rows = db.mark_alert_read(alert_id)
    return rows


@router.post("/alerts/mark-all-read")
def alerts_mark_all_read():
    return db.mark_all_alerts_read()


@router.delete("/alerts/{alert_id}")
def alert_delete_one(alert_id: int, x_acw_token: str | None = Header(default=None, alias="X-ACW-Token")):
    _require_admin(x_acw_token)
    return db.delete_alert(alert_id)


@router.delete("/alerts")
def alerts_delete_all(x_acw_token: str | None = Header(default=None, alias="X-ACW-Token")):
    _require_admin(x_acw_token)
    return db.delete_all_alerts()
