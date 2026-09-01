#!/usr/bin/env python3
"""
Simulator lampu PJU - jadi pengganti ESP32 asli buat tes SELURUH sistem (ingest MQTT,
alert, WebSocket live, kendali dim, jadwal RTC) tanpa perlu hardware nyala. Publish ke
topic MQTT yang SAMA persis dengan firmware asli, backend (mqtt_ingest.py) tidak bisa
bedakan ini dari lampu sungguhan.

Dependency: paho-mqtt, httpx - dua-duanya sudah ada di requirements.txt, nol dependency
baru. Skrip ini SENGAJA standalone (tidak import config.py/db.py dari python-backend) -
device_id disimulasikan bisa jadi "device" dari mesin lain, bukan cuma dari server yang
sama; nilai default di bawah (topic, threshold) MENIRU config.py, bukan membaca
langsung - kalau config.py berubah, sesuaikan juga di sini.

Contoh pakai cepat:
    # 1. Daftarkan dulu (atau pakai --register biar otomatis):
    python tools/simulate_light.py --device-id SIM-01 --register \\
        --admin-user admin --admin-password admin123

    # 2. Kirim telemetry normal terus-menerus tiap 5 detik:
    python tools/simulate_light.py --device-id SIM-01

    # 3. Skenario lonjakan tegangan (buat tes alert):
    python tools/simulate_light.py --device-id SIM-01 --scenario spike --count 3

Lihat TESTING.md (folder sama) buat daftar skenario lengkap & cara verifikasi tiap satu.
"""
from __future__ import annotations

import argparse
import json
import random
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt

try:
    import httpx
except ImportError:
    httpx = None  # cuma dibutuhkan buat --register, sisanya tetap jalan tanpa httpx


# --- Meniru config.py - lihat catatan di docstring atas kenapa tidak import langsung ---
DEFAULT_MQTT_HOST = "broker.emqx.io"
DEFAULT_MQTT_PORT = 1883
TELEMETRY_TOPIC_TEMPLATE = "iot/lights/{device_id}/telemetry"
COMMAND_TOPIC_TEMPLATE = "iot/lights/{device_id}/command"

DEFAULT_SECTOR = "Sektor 1 (Simulasi)"
DEFAULT_LAT = -7.257820
DEFAULT_LNG = 112.737970
DEFAULT_DIM = 80

# Ambang batas alert - PERSIS config.py, dipakai preset --scenario di bawah supaya
# nilainya beneran nembus threshold backend, bukan asal angka besar.
VOLT_SPIKE_THRESHOLD = 240
VOLT_OFFLINE_THRESHOLD = 200
CURRENT_SPIKE_THRESHOLD = 1.5


@dataclass
class SimState:
    """State yang berubah selama simulasi jalan - dim bisa diubah live lewat command
    dari dashboard (lihat _on_command), uptime_hours nambah tiap tick."""
    volt: float
    current: float
    dim: int
    uptime_hours: float
    schedule: list[dict] = field(default_factory=list)


SCENARIOS = {
    # nama: (volt, current) - dim & uptime tetap ikut argumen CLI/state berjalan
    "normal": None,  # None = pakai --volt/--current apa adanya, tanpa override
    "spike": (VOLT_SPIKE_THRESHOLD + 10, None),
    "offline": (VOLT_OFFLINE_THRESHOLD - 20, None),
    "current_spike": (None, CURRENT_SPIKE_THRESHOLD + 0.5),
}


def _register_device(api_url: str, admin_user: str, admin_password: str,
                      device_id: str, sector: str, lat: float, lng: float) -> None:
    """Daftarkan sektor (kalau belum ada) + device lewat API - SAMA jalur yang admin
    beneran pakai (routes_provisioning.py), bukan lewat SQL langsung, supaya validasi
    (charset device_id dkk) ikut ketes juga di jalur ini."""
    if httpx is None:
        print("!! --register butuh 'httpx' terpasang (pip install httpx)", file=sys.stderr)
        sys.exit(1)

    print(f"-> Login sebagai '{admin_user}' ke {api_url} ...")
    r = httpx.post(f"{api_url}/api/login", json={"username": admin_user, "password": admin_password}, timeout=10)
    if r.status_code != 200:
        print(f"!! Login gagal: HTTP {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)
    token = r.json()["token"]
    headers = {"X-ACW-Token": token}

    print(f"-> Pastikan sektor '{sector}' ada ...")
    r = httpx.post(f"{api_url}/api/sectors", json={"sector_name": sector}, headers=headers, timeout=10)
    if r.status_code not in (200, 409):  # 409 = sektor sudah ada, bukan error
        print(f"!! Gagal buat sektor: HTTP {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)

    print(f"-> Daftarkan device '{device_id}' ...")
    r = httpx.post(
        f"{api_url}/api/devices",
        json={"device_id": device_id, "sector_name": sector, "lat": lat, "lng": lng},
        headers=headers, timeout=10,
    )
    if r.status_code == 409:
        print(f"   (device '{device_id}' sudah terdaftar, lanjut apa adanya)")
    elif r.status_code != 200:
        print(f"!! Gagal daftarkan device: HTTP {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"   Device '{device_id}' terdaftar di sektor '{sector}'.")


def _on_command(state: SimState, device_id: str):
    def handler(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"[{device_id}] << command tidak valid JSON, diabaikan")
            return

        if "dim" in payload:
            state.dim = int(payload["dim"])
            print(f"[{device_id}] << terima command DIM baru: {state.dim} "
                  f"(akan terlihat di telemetry berikutnya)")
        if "schedule" in payload:
            state.schedule = payload["schedule"]
            fase = len(state.schedule)
            print(f"[{device_id}] << terima command JADWAL baru: {fase} fase "
                  f"({', '.join(p.get('time', '?') for p in state.schedule)})")
        if "dim" not in payload and "schedule" not in payload:
            print(f"[{device_id}] << command tidak dikenal: {payload}")

    return handler


def _build_payload(device_id: str, sector: str, lat: float, lng: float, state: SimState) -> dict:
    return {
        "id": device_id,
        "sector": sector,
        "lat": lat,
        "lng": lng,
        "volt": round(state.volt, 1),
        "current": round(state.current, 3),
        "power": round(state.volt * state.current, 1),
        "uptime": int(state.uptime_hours * 3600),  # backend minta DETIK, bukan jam
        "dim": state.dim,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device-id", required=True, help="device_id yang disimulasikan (mis. SIM-01)")
    p.add_argument("--sector", default=DEFAULT_SECTOR)
    p.add_argument("--lat", type=float, default=DEFAULT_LAT)
    p.add_argument("--lng", type=float, default=DEFAULT_LNG)
    p.add_argument("--volt", type=float, default=220.0, help="tegangan awal/baseline (V)")
    p.add_argument("--current", type=float, default=0.5, help="arus awal/baseline (A)")
    p.add_argument("--dim", type=int, default=DEFAULT_DIM, help="kecerahan awal (1-10 skala dashboard)")
    p.add_argument("--uptime-hours", type=float, default=0.0,
                   help="jam pakai AWAL - set dekat 8000/10000 buat tes status Warning/Need Maintenance tanpa nunggu beneran")
    p.add_argument("--scenario", choices=list(SCENARIOS.keys()), default="normal",
                   help="normal | spike (>240V) | offline (<200V) | current_spike (>1.5A)")
    p.add_argument("--interval", type=float, default=5.0, help="detik antar publish (default 5)")
    p.add_argument("--count", type=int, default=0, help="jumlah publish lalu berhenti (0 = tanpa batas, Ctrl+C buat stop)")
    p.add_argument("--jitter", type=float, default=0.0,
                   help="variasi acak +/- pada volt/current tiap tick (0 = nilai tetap persis, cocok buat skenario alert biar tidak meleset dari threshold)")
    p.add_argument("--mqtt-host", default=DEFAULT_MQTT_HOST)
    p.add_argument("--mqtt-port", type=int, default=DEFAULT_MQTT_PORT)
    p.add_argument("--register", action="store_true", help="daftarkan sektor+device lewat API sebelum mulai kirim")
    p.add_argument("--api-url", default="http://localhost:8000", help="dipakai kalau --register")
    p.add_argument("--admin-user", default="admin")
    p.add_argument("--admin-password", default="")
    args = p.parse_args()

    if args.register:
        if not args.admin_password:
            print("!! --register butuh --admin-password", file=sys.stderr)
            sys.exit(1)
        _register_device(args.api_url, args.admin_user, args.admin_password,
                          args.device_id, args.sector, args.lat, args.lng)

    scenario = SCENARIOS[args.scenario]
    volt = args.volt if scenario is None or scenario[0] is None else scenario[0]
    current = args.current if scenario is None or scenario[1] is None else scenario[1]
    state = SimState(volt=volt, current=current, dim=args.dim, uptime_hours=args.uptime_hours)

    client_id = f"acw_sim_{args.device_id}_{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(client_id=client_id, clean_session=True)

    telemetry_topic = TELEMETRY_TOPIC_TEMPLATE.format(device_id=args.device_id)
    command_topic = COMMAND_TOPIC_TEMPLATE.format(device_id=args.device_id)

    def on_connect(c, userdata, flags, rc):
        if rc != 0:
            print(f"!! Gagal konek broker, kode {rc}", file=sys.stderr)
            return
        c.subscribe(command_topic, qos=1)
        print(f"-> Terhubung ke {args.mqtt_host}:{args.mqtt_port}, subscribe '{command_topic}'")

    client.on_connect = on_connect
    client.on_message = _on_command(state, args.device_id)

    print(f"=== Simulasi lampu '{args.device_id}' - skenario '{args.scenario}' ===")
    print(f"    Sektor: {args.sector} | Publish ke: {telemetry_topic}")
    print(f"    Volt={state.volt}V Current={state.current}A Dim={state.dim} Uptime={state.uptime_hours}h")
    if args.jitter:
        print(f"    Jitter: +/-{args.jitter}")
    print("    Ctrl+C buat berhenti.\n")

    client.connect(args.mqtt_host, args.mqtt_port, keepalive=60)
    client.loop_start()
    time.sleep(0.5)  # jeda kecil biar CONNACK sempat balik sebelum publish pertama

    stop = {"flag": False}

    def handle_sigint(sig, frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, handle_sigint)

    sent = 0
    try:
        while not stop["flag"]:
            v = state.volt + (random.uniform(-args.jitter, args.jitter) if args.jitter else 0)
            i = state.current + (random.uniform(-args.jitter, args.jitter) if args.jitter else 0)
            tick_state = SimState(volt=v, current=i, dim=state.dim, uptime_hours=state.uptime_hours)
            payload = _build_payload(args.device_id, args.sector, args.lat, args.lng, tick_state)

            client.publish(telemetry_topic, json.dumps(payload), qos=1)
            sent += 1
            print(f"[{args.device_id}] >> #{sent} volt={payload['volt']}V current={payload['current']}A "
                  f"power={payload['power']}W dim={payload['dim']} uptime={payload['uptime']}s")

            state.uptime_hours += args.interval / 3600

            if args.count and sent >= args.count:
                break
            time.sleep(args.interval)
    finally:
        print(f"\n-> Berhenti. Total {sent} pesan terkirim.")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
