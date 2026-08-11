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

from fastapi import APIRouter, Header, HTTPException, Query, Request

import auth
import config
import db
import rate_limit

logger = logging.getLogger("acw.routes.alerts")
router = APIRouter(prefix="/api", tags=["alerts"])

# Endpoint ini publik, jadi `limit` datang dari query string yang bisa diisi siapa saja.
# Tanpa batas atas, satu request `?limit=100000000` cukup buat menarik seluruh tabel
# alerts ke memori proses. Dashboard sendiri paling banyak minta 100 (fetchAlertsFromDB).
# Batasnya di config.MAX_ALERTS_LIMIT - dipakai bersama ai_chat.py (tool get_alerts_history
# jalan ke query yang sama, harus dijaga dua-duanya, bukan cuma jalur HTTP ini).
MAX_ALERTS_LIMIT = config.MAX_ALERTS_LIMIT


def _require_admin(x_acw_token: str | None) -> None:
    if not auth.is_admin(x_acw_token):
        raise HTTPException(status_code=403, detail={"error": "Forbidden: hanya admin yang bisa menghapus alert"})


def _enforce_admin_write_rate_limit(x_acw_token: str | None) -> None:
    # Token sudah lolos _require_admin di titik ini, jadi tidak pernah None - dikunci
    # per-token (bukan IP) supaya kantor sekantor di IP sama tidak saling mentok jatah.
    allowed, retry_after = rate_limit.check(
        "admin_write", x_acw_token,
        config.RATE_LIMIT_ADMIN_WRITE_MAX, config.RATE_LIMIT_ADMIN_WRITE_WINDOW,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": f"Terlalu banyak permintaan. Coba lagi dalam {retry_after} detik."},
        )


def _enforce_public_rate_limit(request: Request) -> None:
    # Tanpa login juga, jadi kena limit sama seperti devices-latest/system-overview -
    # baca DAN tandai-dibaca dua-duanya query Postgres, dua-duanya bisa dipukul
    # berkali-kali per detik tanpa batas ini.
    allowed, retry_after = rate_limit.check(
        "public_read", rate_limit.client_ip(request),
        config.RATE_LIMIT_PUBLIC_MAX, config.RATE_LIMIT_PUBLIC_WINDOW,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": f"Terlalu banyak permintaan. Coba lagi dalam {retry_after} detik."},
        )


@router.get("/alerts-history")
def alerts_history(request: Request, limit: int = Query(default=50, ge=1, le=MAX_ALERTS_LIMIT)):
    _enforce_public_rate_limit(request)
    return db.get_alerts_history(limit)


@router.patch("/alerts/{alert_id}/read")
def alert_mark_read(alert_id: int, request: Request):
    _enforce_public_rate_limit(request)
    rows = db.mark_alert_read(alert_id)
    return rows


@router.post("/alerts/mark-all-read")
def alerts_mark_all_read(request: Request):
    _enforce_public_rate_limit(request)
    return db.mark_all_alerts_read()


@router.delete("/alerts/{alert_id}")
def alert_delete_one(alert_id: int, x_acw_token: str | None = Header(default=None, alias="X-ACW-Token")):
    _require_admin(x_acw_token)
    _enforce_admin_write_rate_limit(x_acw_token)
    return db.delete_alert(alert_id)


@router.delete("/alerts")
def alerts_delete_all(x_acw_token: str | None = Header(default=None, alias="X-ACW-Token")):
    _require_admin(x_acw_token)
    _enforce_admin_write_rate_limit(x_acw_token)
    return db.delete_all_alerts()
