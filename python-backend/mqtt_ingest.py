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

import paho.mqtt.client as mqtt

import alerts
import config
import db
import ws_server

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
    health = alerts.classify_health(data["uptime_hours"])

    try:
        db.upsert_device_and_insert_telemetry(
            device_id, data["sector"], data["lat"], data["lng"],
            data["volt"], data["current"], data["power"], data["uptime_hours"], data["dim"],
        )
    except Exception:
        logger.exception("Gagal simpan telemetry ke Postgres untuk %s", device_id)

    ws_server.broadcast({
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

    ws_server.broadcast({
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


def start() -> mqtt.Client:
    """Konek & mulai network loop di thread background (non-blocking), balikin client-nya."""
    client = mqtt.Client(client_id=config.MQTT_CLIENT_ID, clean_session=True)
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    client.loop_start()
    return client
