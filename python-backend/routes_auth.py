"""
POST /api/login. Setara dengan node "Prepare Login Query" -> "Get User By Username" ->
"Verify Password & Issue Session" di node-red-flow-acw.json, sekarang jadi kode Python
biasa (tidak perlu lagi akal-akalan functionGlobalContext buat akses crypto).
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import auth
import db

logger = logging.getLogger("acw.routes.auth")
router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""


@router.post("/login")
def login(body: LoginRequest):
    username = body.username.strip()
    password = body.password

    if not username or not password:
        raise HTTPException(status_code=400, detail={"error": "Username dan password wajib diisi"})

    user = db.get_user_by_username(username)

    # Pesan generik dibuat sama baik username tidak ada maupun password salah,
    # supaya tidak bisa dipakai menebak username mana yang valid (username enumeration)
    if not user or not auth.verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail={"error": "Username atau password salah"})

    token = auth.issue_session(user["role"])
    return {"role": user["role"], "token": token}
