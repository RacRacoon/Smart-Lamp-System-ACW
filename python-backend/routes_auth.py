"""
POST /api/login. Setara dengan node "Prepare Login Query" -> "Get User By Username" ->
"Verify Password & Issue Session" di node-red-flow-acw.json, sekarang jadi kode Python
biasa (tidak perlu lagi akal-akalan functionGlobalContext buat akses crypto).
"""
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

import auth
import config
import db
import rate_limit

logger = logging.getLogger("acw.routes.auth")
router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""


@router.post("/login")
def login(body: LoginRequest, request: Request):
    # Dibatasi per-IP SEBELUM query database: tanpa ini password admin bisa ditebak
    # secepat jaringan mengizinkan. Kunci rate limit-nya IP, bukan username - kalau
    # dikunci per-username, penyerang justru bisa memakainya buat mengunci akun admin
    # sungguhan dari luar (denial of service ke pemilik akun yang sah).
    allowed, retry_after = rate_limit.check(
        "login", rate_limit.client_ip(request),
        config.RATE_LIMIT_LOGIN_MAX, config.RATE_LIMIT_LOGIN_WINDOW,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": f"Terlalu banyak percobaan login. Coba lagi dalam {retry_after} detik."},
        )

    username = body.username.strip()
    password = body.password

    if not username or not password:
        raise HTTPException(status_code=400, detail={"error": "Username dan password wajib diisi"})

    user = db.get_user_by_username(username)

    # verify_password() SELALU dipanggil, walau username tidak ketemu (pakai
    # auth.DUMMY_HASH) - kalau di-skip lewat "not user or ...", waktu respons jadi beda
    # jauh antara username tidak ada (instan) vs username ada tapi password salah
    # (nunggu argon2id selesai hashing). Pesan errornya sudah sama-sama generik dari
    # dulu, tapi tanpa ini timing-nya sendiri jadi celah enumerasi username.
    password_hash = user["password_hash"] if user else auth.DUMMY_HASH
    password_ok = auth.verify_password(password, password_hash)
    if not user or not password_ok:
        raise HTTPException(status_code=401, detail={"error": "Username atau password salah"})

    # Login berhasil pakai hash lama (scrypt) -> upgrade diam-diam ke argon2id.
    # Password plaintext cuma ada sebentar di request ini, jadi ini satu-satunya
    # kesempatan buat rehash tanpa minta user ganti password manual.
    if auth.is_legacy_hash(user["password_hash"]):
        db.update_password_hash(username, auth.hash_password(password))

    token = auth.issue_session(user["role"])
    return {"role": user["role"], "token": token}


@router.post("/logout")
def logout(x_acw_token: str | None = Header(default=None, alias="X-ACW-Token")):
    # Cabut token di server, bukan cuma hapus di browser - lihat catatan di
    # auth.invalidate_session(). Selalu 200 walau token sudah tidak valid/kosong,
    # supaya klien tidak perlu bedakan "berhasil logout" vs "sesi sudah mati sendiri".
    auth.invalidate_session(x_acw_token)
    return {"ok": True}
