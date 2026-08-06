"""
Subscriber MQTT telemetry lampu. Menggantikan node "Sub Telemetry Semua Lampu"
(11cb04ce0a768f25) + "Parse & Generate SQL Query" (172245d468e0a128) +
"Evaluasi & Build Query Alert" (6a11b6f9dd3cfe32) di node-red-flow-acw.json.

Beda sengaja dari versi Node-RED: delay 1 detik sebelum diproses DIHAPUS (tidak
ada bukti fungsinya, cuma menambah latensi) — telemetry & alert sekarang diproses
begitu pesan MQTT diterima.
"""
import json
import logging
import uuid

import paho.mqtt.client as mqtt

import alerts
import config
import db
import ws_manager

logger = logging.getLogger("acw.mqtt")


def _parse_payload(topic: str, raw: dict) -> dict:
    topic_parts = topic.split("/")
    device_id = raw.get("id") or raw.get("device_id") or (topic_parts[2] if len(topic_parts) > 2 else "UNKNOWN")

    sector = raw.get("sector") or config.DEFAULT_SECTOR
    lat = float(raw.get("lat") or config.DEFAULT_LAT)
    lng = float(raw.get("lng") or config.DEFAULT_LNG)
    volt = float(raw.get("volt") or 0)
    current = float(raw.get("current") or 0)
    power = float(raw.get("power") or (volt * current))

    uptime_seconds = raw.get("uptime")
    uptime_hours = round(uptime_seconds / 3600, 1) if uptime_seconds is not None else 0.0

    dim_raw = raw.get("dim", raw.get("dimming_value", config.DEFAULT_DIM))
    try:
        dim = int(dim_raw)
    except (TypeError, ValueError):
        dim = config.DEFAULT_DIM

    return {
        "device_id": device_id,
        "sector": sector,
        "lat": lat,
        "lng": lng,
        "volt": volt,
        "current": current,
        "power": power,
        "uptime_hours": uptime_hours,
        "dim": dim,
    }


def _handle_telemetry(data: dict) -> None:
    device_id = data["device_id"]

    # Bentuk device_id dicek lebih dulu, dan yang gagal DIBUANG DIAM-DIAM - sengaja tidak
    # bikin alert seperti cabang device tak terdaftar di bawah. Isi alert itu memuat
    # device_id-nya sendiri lalu disimpan permanen + disiarkan ke semua dashboard, jadi
    # kalau ID berisi markup dibuatkan alert, justru jalur itu yang jadi senjatanya.
    # Cukup dicatat ke log (bukan HTML, tidak dirender di mana pun).
    if not config.is_valid_device_id(device_id):
        logger.warning(
            "Telemetry ditolak - bentuk device_id tidak valid (%d karakter, awalan: %r)",
            len(device_id or ""), (device_id or "")[:32],
        )
        return

    # Whitelist: device_id harus sudah diinput manual ke tabel devices lebih dulu.
    # Kalau belum, data ditolak sepenuhnya (tidak masuk telemetry_logs, tidak
    # auto-register) dan dashboard diberi tahu lewat alert - bukan diam-diam dibuang,
    # supaya percobaan kirim data dari device_id asing tetap kelihatan.
    if not db.device_exists(device_id):
        logger.warning("Telemetry ditolak - device_id '%s' belum terdaftar di tabel devices", device_id)
        alert = alerts.unknown_device_alert(device_id)

        try:
            db.insert_alert(
                None, alert["level"], alert["title"], alert["message"],
                data["volt"], data["current"], data["power"], alert["threshold_info"],
            )
        except Exception:
            logger.exception("Gagal simpan alert perangkat tak dikenal untuk %s", device_id)

        # Sengaja TIDAK pakai key "id" di sini - itu trigger dashboard mendaftarkan
        # device baru secara otomatis (lihat socket.onmessage di script.js). Device
        # asing harus tetap muncul di Kotak Peringatan tanpa pernah jadi node yang
        # bisa dikontrol/ditampilkan di peta.
        ws_manager.broadcast({
            "alert": True,
            "device_id": device_id,
            "severity": "critical",
            "alertType": alert["alertType"],
            "level": alert["level"],
            "title": alert["title"],
            "message": alert["message"],
        })
        return

    health = alerts.classify_health(data["uptime_hours"])

    try:
        db.insert_telemetry(
            device_id, data["volt"], data["current"], data["power"], data["uptime_hours"], data["dim"],
        )
    except Exception:
        logger.exception("Gagal simpan telemetry ke Postgres untuk %s", device_id)

    ws_manager.broadcast({
        "id": device_id,
        "device_id": device_id,
        "sector": data["sector"],
        "health": health,
        "uptime": data["uptime_hours"],
        "volt": data["volt"],
        "current": data["current"],
        "power": data["power"],
        "lat": data["lat"],
        "lng": data["lng"],
        "dim": data["dim"],
    })

    alert = alerts.evaluate_alert(device_id, data["volt"], data["current"])
    if not alert:
        return

    try:
        db.insert_alert(
            device_id, alert["level"], alert["title"], alert["message"],
            data["volt"], data["current"], data["power"], alert["threshold_info"],
        )
    except Exception:
        logger.exception("Gagal simpan alert ke Postgres untuk %s", device_id)

    ws_manager.broadcast({
        "id": device_id,
        "alert": True,
        "alertType": alert["alertType"],
        "level": alert["level"],
        "title": alert["title"],
        "message": alert["message"],
        "volt": data["volt"],
        "current": data["current"],
        "power": data["power"],
        "threshold_info": alert["threshold_info"],
    })


def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(config.MQTT_TELEMETRY_TOPIC, qos=1)
        logger.info("Terhubung ke broker MQTT, subscribe topic %s", config.MQTT_TELEMETRY_TOPIC)
    else:
        logger.error("Gagal konek ke broker MQTT, kode: %s", rc)


def _on_message(client, userdata, msg):
    try:
        raw = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Payload MQTT bukan JSON valid dari topic %s", msg.topic)
        return

    try:
        data = _parse_payload(msg.topic, raw)
        _handle_telemetry(data)
    except Exception:
        logger.exception("Gagal memproses pesan telemetry dari topic %s", msg.topic)


_client: mqtt.Client | None = None


def start() -> mqtt.Client:
    """Konek & mulai network loop di thread background (non-blocking), balikin client-nya."""
    global _client
    # Suffix acak per proses - client_id tetap pernah ketabrak sesama instance (restart lama
    # belum lepas, atau dua instance jalan bareng) dan broker.emqx.io menolak terus (CONNACK
    # rc=5, "not authorised") sampai id-nya diganti. Sudah dibuktikan langsung waktu tes.
    client_id = f"{config.MQTT_CLIENT_ID}_{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(client_id=client_id, clean_session=True)
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    client.loop_start()
    _client = client
    return client


def publish_dim_command(device_id: str, dim: int) -> None:
    """Setara dengan node mqtt-out "Publish to MQTT" (POST /api/lights/:id/command).
    Pakai koneksi MQTT yang sama dengan subscriber telemetry, tidak buka koneksi baru."""
    if _client is None:
        raise RuntimeError("MQTT belum konek, panggil start() dulu")
    topic = config.MQTT_COMMAND_TOPIC_TEMPLATE.format(device_id=device_id)
    payload = json.dumps({"dim": dim})
    _client.publish(topic, payload, qos=1, retain=False)


def publish_schedule_command(device_id: str, phases: list[dict]) -> None:
    """Push konfigurasi jadwal RTC (3-6 fase) ke satu device lewat topic command yang
    sama dengan publish_dim_command - firmware ESP32 (modul RTC DS3231) yang
    mengeksekusi tiap fase secara mandiri sesuai jamnya sendiri, backend TIDAK
    nge-trigger dim setiap jam dari sini.

    retain=True (beda dari publish_dim_command yang retain=False): dim command itu
    perintah sesaat, tapi jadwal ini konfigurasi yang harus tetap didapat device
    walau baru nyambung/reconnect setelah broker sempat kirim pesan ini - broker
    simpan pesan retained-nya dan langsung kirim ulang begitu device subscribe."""
    if _client is None:
        raise RuntimeError("MQTT belum konek, panggil start() dulu")
    topic = config.MQTT_COMMAND_TOPIC_TEMPLATE.format(device_id=device_id)
    payload = json.dumps({"schedule": phases})
    _client.publish(topic, payload, qos=1, retain=True)
