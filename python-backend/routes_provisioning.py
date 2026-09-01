"""
GET/POST /api/sectors, POST /api/devices - onboarding sektor & lampu baru.

Sebelum endpoint ini ada, satu-satunya cara mendaftarkan device_id/sektor baru
adalah INSERT manual lewat psql (lihat komentar di db.device_exists()) - gak
praktis buat rollout banyak lampu PJU sungguhan. GET publik (dropdown sektor
dipakai di halaman non-admin juga), POST admin-only sama seperti endpoint lain
yang mengubah data.
"""
import logging

import psycopg2.errors
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

import auth
import config
import db
import rate_limit

logger = logging.getLogger("acw.routes.provisioning")
router = APIRouter(prefix="/api", tags=["provisioning"])

# Nama sektor sengaja TIDAK dibatasi charset seperti device_id - isinya nama jalan
# sungguhan yang wajar pakai spasi/kurung/tanda hubung ("Sektor 2 (Kertajaya - Depan
# ITS)"). Yang dibatasi cuma panjangnya, sisanya diserahkan ke escaping saat render.
MAX_SECTOR_NAME_LENGTH = 120


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


def _enforce_login_rate_limit(request: Request) -> None:
    # Dipakai KHUSUS di delete_sector(): step-up-nya verifikasi ulang password admin,
    # jadi ini secara efektif titik tebak-password kedua di luar /api/login. Kunci &
    # limitnya disamakan (bucket "login", per-IP) supaya tidak jadi jalan pintas
    # brute-force yang lolos dari perlindungan /api/login.
    allowed, retry_after = rate_limit.check(
        "login", rate_limit.client_ip(request),
        config.RATE_LIMIT_LOGIN_MAX, config.RATE_LIMIT_LOGIN_WINDOW,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": f"Terlalu banyak percobaan. Coba lagi dalam {retry_after} detik."},
        )


class CreateSectorRequest(BaseModel):
    sector_name: str


class CreateDeviceRequest(BaseModel):
    device_id: str
    sector_name: str
    lat: float | None = None
    lng: float | None = None
    max_lifespan: int = Field(default=config.DEFAULT_MAX_LIFESPAN, ge=1)


class DeleteSectorRequest(BaseModel):
    # Step-up auth: sesi admin yang masih hidup (X-ACW-Token) TIDAK cukup buat aksi
    # sedestruktif ini - harus buktikan tahu password admin lagi SAAT ITU JUGA (mis.
    # laptop admin ketinggal kebuka bukan berarti siapapun boleh hapus sektor).
    username: str
    password: str


class SectorCreatedResponse(BaseModel):
    sector_name: str


class DeviceCreatedResponse(BaseModel):
    device_id: str
    sector_name: str
    lat: float
    lng: float
    max_lifespan: int


class SectorDeletedResponse(BaseModel):
    sector_name: str
    deleted: bool


@router.get("/sectors", response_model=list[str])
def list_sectors(request: Request):
    _enforce_public_rate_limit(request)
    return db.get_sector_names()


@router.post("/sectors", response_model=SectorCreatedResponse)
def add_sector(
    body: CreateSectorRequest,
    x_acw_token: str | None = Header(default=None, alias="X-ACW-Token"),
):
    if not auth.is_admin(x_acw_token):
        raise HTTPException(status_code=403, detail={"error": "Forbidden: hanya admin yang bisa menambah sektor"})
    _enforce_admin_write_rate_limit(x_acw_token)

    sector_name = body.sector_name.strip()
    if not sector_name:
        raise HTTPException(status_code=400, detail={"error": "Nama sektor tidak boleh kosong"})
    if len(sector_name) > MAX_SECTOR_NAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Nama sektor terlalu panjang (maks {MAX_SECTOR_NAME_LENGTH} karakter)"},
        )

    try:
        db.create_sector(sector_name)
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail={"error": f"Sektor '{sector_name}' sudah terdaftar"})
    except Exception:
        logger.exception("Gagal membuat sektor '%s'", sector_name)
        raise HTTPException(status_code=500, detail={"error": "Gagal menyimpan sektor ke database"})

    return {"sector_name": sector_name}


@router.post("/devices", response_model=DeviceCreatedResponse)
def add_device(
    body: CreateDeviceRequest,
    x_acw_token: str | None = Header(default=None, alias="X-ACW-Token"),
):
    if not auth.is_admin(x_acw_token):
        raise HTTPException(status_code=403, detail={"error": "Forbidden: hanya admin yang bisa mendaftarkan lampu"})
    _enforce_admin_write_rate_limit(x_acw_token)

    device_id = body.device_id.strip()
    if not device_id:
        raise HTTPException(status_code=400, detail={"error": "ID lampu tidak boleh kosong"})

    # Charset yang sama dengan gerbang ingest MQTT - kalau di sini lebih longgar, ID yang
    # ditolak ingest justru bisa didaftarkan admin dan lampunya tidak akan pernah bisa lapor.
    if not config.is_valid_device_id(device_id):
        raise HTTPException(
            status_code=400,
            detail={"error": "ID lampu hanya boleh huruf, angka, titik, garis bawah, dan tanda hubung (maks 64 karakter)"},
        )

    sector_name = body.sector_name.strip()
    if not sector_name:
        raise HTTPException(status_code=400, detail={"error": "Sektor wajib dipilih"})

    # lat/lng kosong -> fallback default (sama dengan yang dipakai mqtt_ingest.py kalau
    # ESP32 belum kirim koordinat) - admin bisa daftarkan dulu, GPS presisi menyusul
    lat = body.lat if body.lat is not None else config.DEFAULT_LAT
    lng = body.lng if body.lng is not None else config.DEFAULT_LNG

    try:
        db.create_device(device_id, sector_name, lat, lng, body.max_lifespan)
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail={"error": f"ID lampu '{device_id}' sudah terdaftar"})
    except psycopg2.errors.ForeignKeyViolation:
        raise HTTPException(status_code=400, detail={"error": f"Sektor '{sector_name}' tidak ditemukan"})
    except Exception:
        logger.exception("Gagal mendaftarkan lampu '%s'", device_id)
        raise HTTPException(status_code=500, detail={"error": "Gagal menyimpan lampu ke database"})

    return {
        "device_id": device_id,
        "sector_name": sector_name,
        "lat": lat,
        "lng": lng,
        "max_lifespan": body.max_lifespan,
    }


@router.delete("/sectors/{sector_name}", response_model=SectorDeletedResponse)
def delete_sector(
    sector_name: str,
    body: DeleteSectorRequest,
    request: Request,
    x_acw_token: str | None = Header(default=None, alias="X-ACW-Token"),
):
    if not auth.is_admin(x_acw_token):
        raise HTTPException(status_code=403, detail={"error": "Forbidden: hanya admin yang bisa menghapus sektor"})

    # Step-up di bawah ini verifikasi ULANG password - titik tebak-password kedua di
    # luar /api/login, jadi dilimit sama seperti login SEBELUM password-nya dicek,
    # bukan sesudah (limit setelah cek tidak berguna, brute force-nya sudah kejadian).
    _enforce_login_rate_limit(request)

    # Step-up: verifikasi ULANG username+password admin, bukan cuma percaya token
    # sesi yang sudah ada. Pesan error digabung (bukan "user tidak ada" vs "password
    # salah" terpisah) - sama alasannya dengan /api/login, jangan bocorin username
    # mana yang valid. verify_password() tetap dipanggil walau user tidak ketemu (pakai
    # auth.DUMMY_HASH) - alasan sama dengan /api/login, cegah enumerasi username lewat
    # timing respons.
    user = db.get_user_by_username(body.username.strip())
    password_hash = user["password_hash"] if user else auth.DUMMY_HASH
    password_ok = auth.verify_password(body.password, password_hash)
    if not user or user["role"] != "admin" or not password_ok:
        raise HTTPException(status_code=401, detail={"error": "Username atau password admin salah"})

    # Blok kalau masih ada lampu di sektor ini - devices.sector_name FK-nya ON DELETE
    # SET NULL, tapi lampu diam-diam kehilangan sektor bukan hasil yang diinginkan;
    # admin harus pindahkan/hapus lampunya dulu secara sadar.
    device_ids = db.get_device_ids_by_sector(sector_name)
    if device_ids:
        raise HTTPException(
            status_code=409,
            detail={"error": f"Sektor ini masih punya {len(device_ids)} lampu terdaftar - pindahkan atau hapus dulu sebelum sektor ini bisa dihapus"},
        )

    try:
        db.delete_sector(sector_name)
    except Exception:
        logger.exception("Gagal menghapus sektor '%s'", sector_name)
        raise HTTPException(status_code=500, detail={"error": "Gagal menghapus sektor dari database"})

    return {"sector_name": sector_name, "deleted": True}
