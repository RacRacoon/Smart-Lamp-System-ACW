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

logger = logging.getLogger("acw.routes.chat")
router = APIRouter(prefix="/api", tags=["chat"])

MAX_MESSAGE_LENGTH = 4000


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = ""
    history: list[ChatMessage] = []


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
