"""
POST /api/chat - endpoint asisten AI dasbor. Publik/read-only (senada dengan
devices-latest & alerts-history), tidak butuh login - cuma bisa BACA data lewat
tool-calling, tidak bisa ubah apapun.
"""
import logging

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import ai_chat
import config
import routes_overview

logger = logging.getLogger("acw.routes.chat")
router = APIRouter(prefix="/api", tags=["chat"])

MAX_MESSAGE_LENGTH = 4000


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = ""
    history: list[ChatMessage] = []


class AnalyzeDeviceRequest(BaseModel):
    device_id: str


@router.post("/chat/analyze-system")
def analyze_system():
    """Kartu "Ringkasan AI" di halaman Dashboard - analisis agregat seluruh sistem.
    Datanya diambil dari routes_overview.system_overview(), fungsi yang sama yang
    mengisi KPI & grafik di halaman itu, supaya angka yang dibahas AI persis sama
    dengan yang sedang dilihat user."""
    if not config.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail={"error": "Asisten AI belum dikonfigurasi di server (GEMINI_API_KEY kosong)"})

    try:
        overview = routes_overview.system_overview()
    except Exception:
        logger.exception("Gagal mengumpulkan ringkasan sistem buat analisis AI")
        raise HTTPException(status_code=500, detail={"error": "Gagal membaca data sistem dari database"})

    if (overview.get("summary", {}).get("total_devices") or 0) == 0:
        raise HTTPException(status_code=409, detail={"error": "Belum ada lampu terdaftar - tidak ada yang bisa dianalisis"})

    try:
        analysis = ai_chat.analyze_system(overview)
    except httpx.HTTPStatusError as e:
        logger.exception("Gemini menolak request analisis sistem")
        raise HTTPException(status_code=502, detail={"error": f"Model AI menolak permintaan (HTTP {e.response.status_code})"})
    except httpx.HTTPError:
        logger.exception("Gagal menghubungi Gemini saat analisis sistem")
        raise HTTPException(status_code=502, detail={"error": "Gagal menghubungi model AI"})

    return {"analysis": analysis}


@router.post("/chat/analyze-device")
def analyze_device(body: AnalyzeDeviceRequest):
    """Tombol "Analisis AI" per kartu lampu di Riwayat Data - satu panggilan non-streaming,
    beda dari /api/chat (tidak ada histori percakapan, tidak ada tool-calling)."""
    device_id = body.device_id.strip()
    if not device_id:
        raise HTTPException(status_code=400, detail={"error": "device_id tidak boleh kosong"})
    if not config.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail={"error": "Asisten AI belum dikonfigurasi di server (GEMINI_API_KEY kosong)"})

    try:
        analysis = ai_chat.analyze_device(device_id)
    except httpx.HTTPStatusError as e:
        logger.exception("Gemini menolak request analisis lampu %s", device_id)
        raise HTTPException(status_code=502, detail={"error": f"Model AI menolak permintaan (HTTP {e.response.status_code})"})
    except httpx.HTTPError:
        logger.exception("Gagal menghubungi Gemini saat analisis lampu %s", device_id)
        raise HTTPException(status_code=502, detail={"error": "Gagal menghubungi model AI"})

    if analysis is None:
        raise HTTPException(status_code=404, detail={"error": f"Lampu '{device_id}' tidak ditemukan"})

    return {"device_id": device_id, "analysis": analysis}


@router.post("/chat")
def chat(body: ChatRequest):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail={"error": "Pesan tidak boleh kosong"})
    if len(message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=400, detail={"error": f"Pesan terlalu panjang (maks {MAX_MESSAGE_LENGTH} karakter)"})
    if not config.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail={"error": "Asisten AI belum dikonfigurasi di server (GEMINI_API_KEY kosong)"})

    history = [m.model_dump() for m in body.history]

    try:
        messages = ai_chat.resolve_tool_calls(message, history)
    except httpx.HTTPStatusError as e:
        logger.exception("Gemini menolak request tool-calling")
        raise HTTPException(status_code=502, detail={"error": f"Model AI menolak permintaan (HTTP {e.response.status_code})"})
    except httpx.HTTPError:
        logger.exception("Gagal menghubungi Gemini saat resolusi tool call")
        raise HTTPException(status_code=502, detail={"error": "Gagal menghubungi model AI"})

    def event_stream():
        try:
            with ai_chat.stream_final_answer(messages) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes():
                    yield chunk
        except Exception:
            logger.exception("Gagal streaming jawaban akhir chat AI")
            yield b'data: {"error": "Koneksi ke model AI terputus di tengah jalan"}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")
