"""
Asisten AI dasbor. Jawaban di-grounding ke data live di Postgres lewat tool-calling
(OpenAI-compatible function calling) ke endpoint OpenAI-compatible resmi Gemini -
bukan API Anthropic, model yang dipakai Gemini 2.5 Flash (free tier), atas
permintaan eksplisit.

Alur: resolve_tool_calls() jalanin loop tool-calling NON-streaming dulu (lebih gampang
diperiksa - tidak perlu rakit ulang tool_call yang datangnya kepotong-potong di tengah
SSE), sampai model tidak minta tool lagi. Baru setelah itu stream_final_answer()
dipanggil TANPA daftar tools (dipaksa jawab teks polos) dan di-stream ke frontend biar
kelihatan mengetik langsung.
"""
import json
import logging

import httpx

import config
import db

logger = logging.getLogger("acw.ai_chat")

SYSTEM_PROMPT = (
    "Kamu asisten AI untuk dasbor Manajemen Lampu Kota (sistem pemantauan lampu jalan "
    "pintar). Jawab pertanyaan user HANYA berdasarkan data yang kamu ambil lewat tool "
    "yang tersedia - jangan mengarang angka. Kalau pertanyaan menyebut ID lampu spesifik "
    "(contoh L-107), pakai ID itu apa adanya. Kalau user tidak menyebut lampu mana, "
    "cek dulu daftar lampu lewat get_devices_latest sebelum menjawab. Jawab singkat, "
    "jelas, dan dalam Bahasa Indonesia. Kalau data yang diminta tidak ada/tidak "
    "ditemukan, bilang terus terang, jangan menebak-nebak."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_devices_latest",
            "description": (
                "Ambil status & telemetry terbaru SEMUA lampu terdaftar: id, sektor, "
                "lokasi GPS, tegangan, arus, daya, uptime, tingkat kecerahan (dim)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_telemetry_history",
            "description": (
                "Ambil riwayat telemetry (tegangan/arus/daya per waktu, maksimal 100 "
                "titik terakhir) untuk SATU lampu tertentu."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "ID lampu, contoh: L-107"},
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alerts_history",
            "description": "Ambil daftar peringatan/alert terakhir dari semua lampu, terbaru dulu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Jumlah maksimal alert diambil, default 20"},
                },
                "required": [],
            },
        },
    },
]

MAX_TOOL_ROUNDS = 4


def _execute_tool(name: str, args: dict) -> object:
    try:
        if name == "get_devices_latest":
            return db.get_devices_latest()
        if name == "get_telemetry_history":
            device_id = str(args.get("device_id", "")).strip()
            if not device_id:
                return {"error": "device_id wajib diisi"}
            return db.get_telemetry_history(device_id)
        if name == "get_alerts_history":
            try:
                limit = int(args.get("limit", 20))
            except (TypeError, ValueError):
                limit = 20
            return db.get_alerts_history(limit)
        return {"error": f"Tool tidak dikenal: {name}"}
    except Exception:
        logger.exception("Tool '%s' gagal dieksekusi (args=%s)", name, args)
        return {"error": "Gagal mengambil data dari database"}


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.GEMINI_API_KEY}",
        "Content-Type": "application/json",
    }


def _call_gemini(messages: list[dict], with_tools: bool) -> dict:
    # reasoning_effort "low": default thinking Gemini bisa >50 detik cuma buat jawaban
    # singkat - jauh lebih lambat dari yang dibutuhkan buat chat dasbor semacam ini.
    payload = {
        "model": config.GEMINI_MODEL,
        "messages": messages,
        "reasoning_effort": "low",
    }
    if with_tools:
        payload["tools"] = TOOLS
    resp = httpx.post(
        f"{config.GEMINI_BASE_URL}/chat/completions",
        headers=_headers(), json=payload, timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def resolve_tool_calls(user_message: str, history: list[dict]) -> list[dict]:
    """Jalankan loop tool-calling sampai model berhenti minta tool (atau kehabisan
    jatah putaran). Return messages siap dipakai buat panggilan streaming terakhir."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    for _ in range(MAX_TOOL_ROUNDS):
        data = _call_gemini(messages, with_tools=True)
        choice = data["choices"][0]
        msg = choice["message"]
        tool_calls = msg.get("tool_calls")

        if not tool_calls:
            return messages

        messages.append({
            "role": "assistant",
            "content": msg.get("content"),
            "tool_calls": tool_calls,
        })

        for call in tool_calls:
            fn = call["function"]
            name = fn["name"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _execute_tool(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result, default=str),
            })

    return messages


def stream_final_answer(messages: list[dict]):
    """Context manager httpx buat request streaming - dipanggil dengan 'with' di
    routes_chat.py. Sengaja tanpa 'tools' supaya putaran terakhir ini pasti jawaban
    teks, bukan tool_call lagi (kalau masih ada tool_call di tengah stream, parsing
    di sisi frontend jadi jauh lebih rumit)."""
    payload = {
        "model": config.GEMINI_MODEL,
        "messages": messages,
        "stream": True,
        "reasoning_effort": "low",
    }
    return httpx.stream(
        "POST", f"{config.GEMINI_BASE_URL}/chat/completions",
        headers=_headers(), json=payload, timeout=60.0,
    )
