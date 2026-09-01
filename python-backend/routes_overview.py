"""
GET /api/system-overview - agregat seluruh sistem buat halaman Dashboard (beranda).
Publik/read-only, senada dengan devices-latest & alerts-history.

Semua angka di sini dihitung dari isi tabel devices/sectors/telemetry_logs/alerts -
tidak ada nilai contoh atau placeholder. Kalau tabelnya masih kosong, hasilnya
memang nol/array kosong, dan frontend yang menampilkan empty state.
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import alerts
import config
import db
import rate_limit

logger = logging.getLogger("acw.routes.overview")
router = APIRouter(prefix="/api", tags=["overview"])

# Jumlah bucket rata-rata per jam yang dikirim ke grafik telemetry Dashboard
AVG_TELEMETRY_BUCKETS = 48


class OverviewSummary(BaseModel):
    total_devices: int
    total_sectors: int
    reporting_devices: int
    total_power: float
    avg_volt: float
    avg_current: float
    alerts_total: int
    alerts_unread: int
    # Kunci "Need Maintenance" ada spasi - tidak bisa jadi nama field Python langsung,
    # dict[str, int] lebih jujur daripada field alias yang kaku buat 3 kunci tetap ini.
    health_totals: dict[str, int]


class SectorHealth(BaseModel):
    sector: str
    lamp_count: int
    health: dict[str, int]


class AvgTelemetryPoint(BaseModel):
    # TIDAK ada field "bucket" - db.get_average_telemetry() sengaja pop() kolom itu
    # sebelum dikembalikan (cuma dipakai buat ORDER BY internal, bukan buat frontend).
    # Ketahuan langsung dari uji lawan data live (server 500, ResponseValidationError
    # "bucket: Field required") - baru dibetulkan di sini, bukan skema baru diimprovisasi.
    time_label: str
    avg_volt: float
    avg_current: float
    avg_power: float
    device_count: int


class SystemOverviewResponse(BaseModel):
    summary: OverviewSummary
    sectors: list[SectorHealth]
    avg_telemetry: list[AvgTelemetryPoint]


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


@router.get("/system-overview", response_model=SystemOverviewResponse)
def system_overview(request: Request):
    _enforce_public_rate_limit(request)
    return compute_system_overview()


def compute_system_overview():
    """Logika agregasi murni, dipisah dari handler HTTP supaya bisa dipanggil langsung
    oleh routes_chat.py (analisis AI) tanpa lewat rate limit endpoint publik - jalur AI
    sudah punya limitnya sendiri (bucket "ai" di config.RATE_LIMIT_AI_*)."""
    devices = db.get_devices_latest()
    lamp_states = db.get_sector_lamp_states()
    avg_telemetry = db.get_average_telemetry(AVG_TELEMETRY_BUCKETS)
    alert_counts = db.get_alert_counts()

    # --- Ringkasan per sektor: jumlah lampu + rincian kesehatannya ---
    # Baris dengan device_id NULL = sektor terdaftar yang belum punya lampu sama
    # sekali (LEFT JOIN di get_sector_lamp_states), jadi dihitung 0, bukan 1.
    sectors: dict[str, dict] = {}
    for row in lamp_states:
        name = row["sector_name"]
        if name not in sectors:
            sectors[name] = {
                "sector": name,
                "lamp_count": 0,
                "health": {"Healthy": 0, "Warning": 0, "Need Maintenance": 0},
            }
        if row["device_id"] is None:
            continue
        sectors[name]["lamp_count"] += 1
        status = alerts.classify_health(float(row["uptime"] or 0))
        sectors[name]["health"][status] += 1

    # --- KPI sistem: dihitung dari pembacaan TERBARU tiap lampu ---
    total_power = sum(float(d["power"] or 0) for d in devices)
    # Rata-rata tegangan/arus sengaja cuma dari lampu yang sedang melapor (volt > 0).
    # Lampu yang belum pernah kirim telemetry punya volt = 0 (COALESCE di query), kalau
    # ikut dirata-rata malah menyeret angkanya turun seolah tegangannya benar-benar drop.
    reporting = [d for d in devices if float(d["volt"] or 0) > 0]
    avg_volt = sum(float(d["volt"]) for d in reporting) / len(reporting) if reporting else 0
    avg_current = sum(float(d["current"] or 0) for d in reporting) / len(reporting) if reporting else 0

    health_totals = {"Healthy": 0, "Warning": 0, "Need Maintenance": 0}
    for s in sectors.values():
        for k, v in s["health"].items():
            health_totals[k] += v

    return {
        "summary": {
            "total_devices": len(devices),
            "total_sectors": len(sectors),
            "reporting_devices": len(reporting),
            "total_power": round(total_power, 2),
            "avg_volt": round(avg_volt, 2),
            "avg_current": round(avg_current, 3),
            "alerts_total": int(alert_counts.get("total", 0) or 0),
            "alerts_unread": int(alert_counts.get("unread", 0) or 0),
            "health_totals": health_totals,
        },
        "sectors": sorted(sectors.values(), key=lambda s: s["sector"]),
        "avg_telemetry": avg_telemetry,
    }
