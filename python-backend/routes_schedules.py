"""
GET/PUT jadwal kecerahan & kehangatan warna per sektor (fase RTC) - halaman
Kelola Lampu di dashboard. Baca publik (panel detail lampu di halaman Beranda juga
menampilkan jadwal ini ke SEMUA role, bukan cuma admin), ubah admin-only lewat token
sesi - sama persis pola aksesnya dengan POST /api/lights/:id/command.
"""
import logging

import psycopg2.errors
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import auth
import db
import mqtt_ingest

logger = logging.getLogger("acw.routes.schedules")
router = APIRouter(prefix="/api", tags=["schedules"])

MIN_PHASES = 3
MAX_PHASES = 6


class SchedulePhase(BaseModel):
    time: str
    dim: int = Field(ge=1, le=10)
    cct: int = Field(ge=0, le=100)


class SectorScheduleUpdate(BaseModel):
    sector: str
    schedules: list[SchedulePhase]


@router.get("/sector-schedules")
def sector_schedules():
    """Kelompokkan baris flat dari DB jadi {nama_sektor: [fase, ...]} - query sudah
    ORDER BY sector_name, schedule_time jadi tiap grup otomatis terurut kronologis."""
    rows = db.get_sector_schedules()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["sector_name"], []).append(
            {"time": row["time"], "dim": row["dim"], "cct": row["cct"]}
        )
    return grouped


@router.put("/sector-schedules")
def update_sector_schedule(
    body: SectorScheduleUpdate,
    x_acw_token: str | None = Header(default=None, alias="X-ACW-Token"),
):
    if not auth.is_admin(x_acw_token):
        raise HTTPException(status_code=403, detail={"error": "Forbidden: hanya admin yang bisa mengubah jadwal"})

    if not (MIN_PHASES <= len(body.schedules) <= MAX_PHASES):
        raise HTTPException(
            status_code=400,
            detail={"error": f"Jumlah fase harus antara {MIN_PHASES} dan {MAX_PHASES}"},
        )

    phases = [p.model_dump() for p in body.schedules]

    try:
        db.replace_sector_schedule(body.sector, phases)
    except psycopg2.errors.ForeignKeyViolation:
        raise HTTPException(status_code=400, detail={"error": f"Sektor '{body.sector}' tidak terdaftar"})
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail={"error": "Ada dua fase dengan jam mulai yang sama - tiap fase harus punya jam mulai berbeda"})
    except Exception:
        logger.exception("Gagal simpan jadwal sektor '%s'", body.sector)
        raise HTTPException(status_code=500, detail={"error": "Gagal menyimpan jadwal ke database"})

    # Jadwal SUDAH tersimpan di DB di titik ini - kegagalan publish MQTT di bawah tidak
    # membatalkan penyimpanan, cuma dicatat, supaya admin tidak kehilangan editan-nya
    # gara-gara broker sedang bermasalah (device akan dapat versi terbaru saat reconnect
    # berkat retain=True, atau saat sektornya disimpan ulang).
    for device_id in db.get_device_ids_by_sector(body.sector):
        try:
            mqtt_ingest.publish_schedule_command(device_id, phases)
        except Exception:
            logger.exception("Gagal publish jadwal ke device '%s' (sektor '%s')", device_id, body.sector)

    return {"sector": body.sector, "schedules": phases}
