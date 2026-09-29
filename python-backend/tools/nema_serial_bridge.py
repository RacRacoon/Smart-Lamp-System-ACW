#!/usr/bin/env python3
"""Jembatan sementara: konsol UART papan NEMA -> broker MQTT -> backend.

Dipakai selama modem Quectel di papan belum punya kartu SIM aktif. Papan tidak
diubah sama sekali: skrip ini hanya mengetikkan perintah `s` ke konsol seperti
manusia, membaca laporan statusnya, lalu menerbitkannya sebagai telemetri.

Begitu kartu baru terpasang, papan menerbitkan sendiri lewat AT+QMTPUB dan
skrip ini tidak diperlukan lagi - bentuk muatannya sudah sama persis.

    python tools/nema_serial_bridge.py --port COM6 --device NEMA-01

Ctrl+C untuk berhenti.
"""

import argparse
import json
import re
import sys
import time

import serial
import paho.mqtt.client as mqtt

# Baris status dicetak dengan lebar kolom tetap, tapi angkanya dicomot dengan
# regex per jenis baris, bukan dengan memotong pada posisi kolom - kalau nanti
# lebar kolomnya dirapikan lagi di firmware, skrip ini tidak ikut rusak.
RE_LAMP = re.compile(r"^LAMP\s+([\d.]+)\s*%\s+(\d+)\s*mV")
RE_LIGHT = re.compile(r"^LIGHT\s+raw\s+(\d+)\s+(\d+)\s*mV\s+(\d+)\s*%")
RE_CLIMATE = re.compile(
    r"^CLIMATE\s+Temperature\s+(-?[\d.]+)\s*C\s+Relative Humidity\s+([\d.]+)\s*%"
)
RE_TILT = re.compile(
    r"^TILT\s+X\s+(-?\d+)\s+Y\s+(-?\d+)\s+Z\s+(-?\d+)\s*mg(?:\s+(-?\d+)\s*deg)?"
)
RE_RELAY = re.compile(r"^RELAY\s+(on|off)")
RE_TIME = re.compile(r"^TIME\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

# MAINS punya dua bentuk: lengkap dengan arus, atau hanya tegangan bila beban nol.
RE_MAINS_FULL = re.compile(
    r"^MAINS\s+([\d.]+)\s*V\s+([\d.]+)\s*A\s+([\d.]+)\s*W\s+([\d.]+)\s*VA\s+PF\s+([\d.]+|n/a)"
)
RE_MAINS_V = re.compile(r"^MAINS\s+([\d.]+)\s*V")


def read_status(ser, timeout=6.0):
    """Ketik `s`, kumpulkan laporannya sampai baris LOGS atau waktu habis."""
    ser.reset_input_buffer()
    ser.write(b"s\r")
    lines = []
    deadline = time.time() + timeout
    buf = ""
    while time.time() < deadline:
        chunk = ser.read(256)
        if chunk:
            buf += chunk.decode("ascii", errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip("\r> ").strip()
                if line:
                    lines.append(line)
            # LOGS adalah baris terakhir print_status(), jadi laporan sudah utuh.
            if any(l.startswith("LOGS") for l in lines):
                break
        else:
            time.sleep(0.05)
    return lines


def parse_status(lines):
    """Ubah laporan konsol jadi dict. Nilai yang tidak terbaca ditinggal kosong."""
    out = {}
    for line in lines:
        m = RE_LAMP.match(line)
        if m:
            out["dim"] = int(round(float(m.group(1))))
            out["driver_mv"] = int(m.group(2))
            continue
        m = RE_LIGHT.match(line)
        if m:
            out["ldr_raw"] = int(m.group(1))
            out["ldr_mv"] = int(m.group(2))
            out["ldr_pct"] = int(m.group(3))
            continue
        m = RE_CLIMATE.match(line)
        if m:
            out["temp_c"] = float(m.group(1))
            out["humidity"] = float(m.group(2))
            continue
        m = RE_TILT.match(line)
        if m:
            out["tilt_mg"] = [int(m.group(1)), int(m.group(2)), int(m.group(3))]
            if m.group(4) is not None:
                out["tilt_deg"] = int(m.group(4))
            continue
        m = RE_RELAY.match(line)
        if m:
            out["relay"] = m.group(1)
            continue
        m = RE_TIME.match(line)
        if m:
            out["rtc"] = m.group(1)
            continue
        if line.startswith("MAINS"):
            m = RE_MAINS_FULL.match(line)
            if m:
                out["volt"] = float(m.group(1))
                out["current"] = float(m.group(2))
                out["power"] = float(m.group(3))
                out["va"] = float(m.group(4))
                if m.group(5) != "n/a":
                    out["pf"] = float(m.group(5))
                continue
            m = RE_MAINS_V.match(line)
            if m:
                out["volt"] = float(m.group(1))
                out["current"] = 0.0
                out["power"] = 0.0
                continue
            # "no mains voltage...", "meter silent...", "no meter frame yet"
            out["mains_note"] = line[5:].strip()
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--port", default="COM6", help="port konsol papan (default COM6)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--device", default="NEMA-01", help="device_id yang sudah terdaftar")
    ap.add_argument("--sector", default="Sektor 2 (Kertajaya - Depan ITS)")
    ap.add_argument("--lat", type=float, default=-7.279315)
    ap.add_argument("--lng", type=float, default=112.789253)
    ap.add_argument("--broker", default="broker.emqx.io")
    ap.add_argument("--broker-port", type=int, default=1883)
    ap.add_argument("--interval", type=float, default=10.0, help="jeda antar kiriman, detik")
    ap.add_argument("--once", action="store_true", help="kirim sekali lalu keluar")
    ap.add_argument("--dry-run", action="store_true", help="tampilkan muatan, jangan kirim")
    args = ap.parse_args()

    topic = "iot/lights/%s/telemetry" % args.device

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.2)
    except serial.SerialException as exc:
        print("Tidak bisa membuka %s: %s" % (args.port, exc), file=sys.stderr)
        print("Tutup dulu serial monitor yang lain.", file=sys.stderr)
        return 1

    client = None
    if not args.dry_run:
        client = mqtt.Client(client_id="nema-bridge-%s" % args.device)
        client.connect(args.broker, args.broker_port, 30)
        client.loop_start()
        print("terhubung ke %s:%d, topik %s" % (args.broker, args.broker_port, topic))

    # Papan tidak melaporkan uptime-nya sendiri, jadi yang dihitung adalah lama
    # jembatan ini hidup. Cukup untuk kolom health di dashboard, dan akan
    # digantikan angka asli dari papan begitu ia menerbitkan sendiri.
    started = time.time()
    time.sleep(0.5)

    try:
        while True:
            lines = read_status(ser)
            if not lines:
                print("papan diam - konsol tidak menjawab `s`")
            else:
                st = parse_status(lines)
                payload = {
                    "id": args.device,
                    "sector": args.sector,
                    "lat": args.lat,
                    "lng": args.lng,
                    "volt": st.get("volt", 0.0),
                    "current": st.get("current", 0.0),
                    "power": st.get("power", 0.0),
                    "dim": st.get("dim", 0),
                    "uptime": int(time.time() - started),
                }
                # Bidang tambahan ikut dikirim: backend mengabaikan yang tidak
                # dikenalnya, tapi datanya terlihat di broker saat menelusuri.
                for k in ("pf", "va", "temp_c", "humidity", "ldr_raw", "ldr_pct",
                          "tilt_deg", "relay", "rtc", "mains_note"):
                    if k in st:
                        payload[k] = st[k]

                blob = json.dumps(payload)
                if args.dry_run:
                    print(blob)
                else:
                    client.publish(topic, blob, qos=1)
                    print("%s  terkirim: %.1f V  %.3f A  %.1f W  dim %d%%" % (
                        time.strftime("%H:%M:%S"), payload["volt"], payload["current"],
                        payload["power"], payload["dim"]))
                    if "mains_note" in payload:
                        print("            catatan meter: %s" % payload["mains_note"])

            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nberhenti.")
    finally:
        ser.close()
        if client is not None:
            client.loop_stop()
            client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
