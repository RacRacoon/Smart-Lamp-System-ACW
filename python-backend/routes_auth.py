"""
POST /api/login. Setara dengan node "Prepare Login Query" -> "Get User By Username" ->
"Verify Password & Issue Session" di node-red-flow-acw.json, sekarang jadi kode Python
biasa (tidak perlu lagi akal-akalan functionGlobalContext buat akses crypto).
"""
import logging

from fastapi import APIRouter, HTTPException, Request
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

    # Pesan generik dibuat sama baik username tidak ada maupun password salah,
    # supaya tidak bisa dipakai menebak username mana yang valid (username enumeration)
    if not user or not auth.verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail={"error": "Username atau password salah"})

    # Login berhasil pakai hash lama (scrypt) -> upgrade diam-diam ke argon2id.
    # Password plaintext cuma ada sebentar di request ini, jadi ini satu-satunya
    # kesempatan buat rehash tanpa minta user ganti password manual.
    if auth.is_legacy_hash(user["password_hash"]):
        db.update_password_hash(username, auth.hash_password(password))

    token = auth.issue_session(user["role"])
    return {"role": user["role"], "token": token}
