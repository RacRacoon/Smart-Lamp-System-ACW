#!/usr/bin/env python3
"""Jembatan sementara dua arah antara papan NEMA dan dashboard.

Naik  : konsol UART papan -> broker MQTT -> backend -> dashboard
Turun : slider Kendali Cepat -> backend -> broker -> konsol UART papan

Dipakai selama modem Quectel di papan belum punya kartu SIM aktif. Papan tidak
diubah sama sekali: skrip ini mengetikkan perintah ke konsol seperti manusia -
`s` untuk membaca status, `d <permil>` untuk mengubah kecerahan.

Begitu kartu baru terpasang, papan menerbitkan sendiri lewat AT+QMTPUB dan
skrip ini tidak diperlukan lagi - bentuk muatannya sudah sama persis.

    python tools/nema_serial_bridge.py --port COM6 --device NEMA-01

Ctrl+C untuk berhenti.
"""

import argparse
import json
import re
import sys
import threading
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
RE_AUTO = re.compile(r"^AUTO\s+(on|off)")
RE_TIME = re.compile(r"^TIME\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
# "GPS  fix 1   5 of 9 sats   -7.314990  112.789501   alt 12 m ..."
# Bentuk "N of M sats" menggantikan "N sats" begitu firmware mulai membedakan
# satelit yang DIPAKAI dari yang TERLIHAT. Keduanya diterima di sini supaya
# jembatan ini tidak buta terhadap papan yang firmware-nya belum diperbarui.
RE_GPS = re.compile(
    r"^GPS\s+fix\s+(\d+)\s+(\d+)(?:\s+of\s+(\d+))?\s*sats\s+"
    r"(-?[\d.]+)\s+(-?[\d.]+)\s+alt\s+(-?\d+)\s*m"
)

# "site -7.314990  112.789501   (saved)" - letak tiang yang tersimpan di flash
# papan. Dipakai saat GPS belum mengunci, dan lebih dipercaya daripada angka
# bawaan di baris perintah: yang tahu letaknya adalah papan itu sendiri.
RE_SITE = re.compile(r"^site\s+(-?[\d.]+)\s+(-?[\d.]+)")

# MAINS punya dua bentuk: lengkap dengan arus, atau hanya tegangan bila beban nol.
RE_MAINS_FULL = re.compile(
    r"^MAINS\s+([\d.]+)\s*V\s+([\d.]+)\s*A\s+([\d.]+)\s*W\s+([\d.]+)\s*VA\s+PF\s+([\d.]+|n/a)"
)
RE_MAINS_V = re.compile(r"^MAINS\s+([\d.]+)\s*V")


def open_port(port, baud, give_up=False, quiet_after=5):
    """Buka port konsol, dan tunggu kalau belum ada.

    Dipanggil saat mulai dan setiap kali port hilang di tengah jalan. Menyerah
    seketika akan membuat jembatan ini tidak bisa dijalankan otomatis saat
    Windows menyala: papan sering belum dikenali saat itu, dan kabel USB-TTL
    dicabut-colok sepanjang hari. Jadi ia menunggu, dan berhenti mengeluh
    setelah beberapa percobaan supaya jendelanya tidak dipenuhi pesan sama.
    """
    tries = 0
    while True:
        try:
            return serial.Serial(port, baud, timeout=0.2)
        except serial.SerialException as exc:
            tries += 1
            if give_up:
                print("Tidak bisa membuka %s: %s" % (port, exc), file=sys.stderr)
                print("Tutup dulu serial monitor yang lain.", file=sys.stderr)
                return None
            if tries <= quiet_after:
                print("menunggu %s - %s" % (port, str(exc).split(":")[0]))
                if tries == quiet_after:
                    print("(pesan yang sama tidak diulang lagi, tetap mencoba)")
            time.sleep(3)


# Konsol papan hanya satu jalur, tapi dipakai dua pihak: loop utama yang
# bertanya `s` tiap beberapa detik, dan callback MQTT yang datang dari thread
# jaringan membawa perintah dari dashboard. Tanpa kunci ini keduanya bisa menulis
# bersamaan dan jawabannya tercampur - perintah setengah terkirim, status
# setengah terbaca.
ser_lock = threading.Lock()


def send_command(ser, line):
    """Ketikkan satu perintah ke konsol papan, lalu baca jawabannya sebentar."""
    with ser_lock:
        ser.reset_input_buffer()
        ser.write((line + "\r").encode("ascii", errors="ignore"))
        time.sleep(0.4)
        reply = ser.read(512).decode("ascii", errors="replace")
    return " | ".join(
        x.strip() for x in reply.replace("\r", "").split("\n") if x.strip()
    )


def set_auto(ser, want):
    """Setel mode otomatis LDR ke keadaan yang diminta, bukan menjungkitnya.

    Perintah `m` di papan MENJUNGKIT. Dari dashboard itu berbahaya: menekan
    "nyalakan auto" saat papan sudah auto justru mematikannya, dan pengirim
    perintah tidak pernah tahu keadaan papan sekarang.

    Jadi keadaannya dibaca dulu, lalu `m` dikirim hanya kalau memang berbeda.
    Cara ini juga tidak bergantung pada versi program di papan - firmware yang
    lebih baru menerima `m 1`/`m 0` secara eksplisit, yang lama tidak, dan
    keduanya sama-sama benar lewat jalur ini.
    """
    with ser_lock:
        lines = read_status(ser)
    now = parse_status(lines).get("auto")

    if now is None:
        return "papan tidak melaporkan baris AUTO"
    if now == want:
        return "sudah %s, tidak diubah" % ("on" if want else "off")

    reply = send_command(ser, "m")
    return reply or "(papan diam)"


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
        m = RE_AUTO.match(line)
        if m:
            out["auto"] = (m.group(1) == "on")
            continue
        m = RE_TIME.match(line)
        if m:
            out["rtc"] = m.group(1)
            continue
        m = RE_GPS.match(line)
        if m:
            out["gps_fix"] = int(m.group(1))
            out["gps_sats"] = int(m.group(2))
            if m.group(3) is not None:
                out["gps_view"] = int(m.group(3))
            out["lat"] = float(m.group(4))
            out["lng"] = float(m.group(5))
            out["alt_m"] = int(m.group(6))
            continue
        m = RE_SITE.match(line)
        if m:
            out["site_lat"] = float(m.group(1))
            out["site_lng"] = float(m.group(2))
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
    # Tanpa nilai bawaan, dan itu disengaja. Papan sudah menyimpan letaknya
    # sendiri di flash (gps save) dan melaporkannya di baris status, jadi
    # koordinat yang ditulis di sini hanya akan jadi angka basi yang diam-diam
    # menimpa kebenaran. Isi hanya kalau papan memang belum tahu letaknya dan
    # kau ingin memaksanya sementara.
    ap.add_argument("--lat", type=float, default=None)
    ap.add_argument("--lng", type=float, default=None)
    ap.add_argument("--broker", default="broker.emqx.io")
    ap.add_argument("--broker-port", type=int, default=1883)
    ap.add_argument("--interval", type=float, default=10.0, help="jeda antar kiriman, detik")
    ap.add_argument("--once", action="store_true", help="kirim sekali lalu keluar")
    ap.add_argument("--dry-run", action="store_true", help="tampilkan muatan, jangan kirim")
    args = ap.parse_args()

    topic = "iot/lights/%s/telemetry" % args.device

    ser = open_port(args.port, args.baud, give_up=args.once)
    if ser is None:
        return 1

    cmd_topic = "iot/lights/%s/command" % args.device

    def on_command(_client, _userdata, msg):
        """Terjemahkan perintah dashboard jadi ketikan di konsol papan.

        Dashboard memakai persen (0-100), papan memakai per mil (0-1000), jadi
        dikalikan sepuluh. Perintah jadwal ikut lewat topik yang sama dan
        dikirim retained, artinya satu pesan lama bisa langsung datang begitu
        skrip ini menyambung - diabaikan dengan tenang, bukan dianggap galat.
        """
        try:
            body = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except ValueError:
            print("perintah tidak terbaca: %r" % msg.payload[:80])
            return

        if "auto" in body:
            want = bool(body["auto"])
            reply = set_auto(ser, want)
            print("%s  terima perintah auto %s -> %s" % (
                time.strftime("%H:%M:%S"), "on" if want else "off", reply))
            # Perintah auto boleh datang bersama dim; kalau hanya auto, selesai.
            if "dim" not in body:
                return

        if "dim" not in body:
            # Kemungkinan perintah jadwal (phases). Papan ini belum menjalankan
            # jadwal sendiri, jadwalnya masih dari LDR.
            print("perintah tanpa 'dim' diabaikan: %s" % sorted(body)[:6])
            return

        try:
            pct = int(body["dim"])
        except (TypeError, ValueError):
            print("nilai dim tidak sah: %r" % body.get("dim"))
            return
        pct = max(0, min(100, pct))

        reply = send_command(ser, "d %d" % (pct * 10))
        print("%s  terima perintah dim %d%% -> %s" % (
            time.strftime("%H:%M:%S"), pct, reply or "(papan diam)"))

    client = None
    if not args.dry_run:
        client = mqtt.Client(client_id="nema-bridge-%s" % args.device)
        client.on_message = on_command
        client.connect(args.broker, args.broker_port, 30)
        client.subscribe(cmd_topic, qos=1)
        client.loop_start()
        print("terhubung ke %s:%d" % (args.broker, args.broker_port))
        print("  kirim  -> %s" % topic)
        print("  dengar <- %s" % cmd_topic)

    # Papan tidak melaporkan uptime-nya sendiri, jadi yang dihitung adalah lama
    # jembatan ini hidup. Cukup untuk kolom health di dashboard, dan akan
    # digantikan angka asli dari papan begitu ia menerbitkan sendiri.
    started = time.time()
    time.sleep(0.5)

    try:
        while True:
            try:
                with ser_lock:
                    lines = read_status(ser)
            except (serial.SerialException, OSError) as exc:
                # Kabel dicabut, atau papan di-flash ulang. Bukan alasan berhenti:
                # port itu akan muncul lagi dengan nama yang sama.
                print("port %s hilang (%s), menunggu kembali" % (args.port, exc))
                try:
                    ser.close()
                except Exception:
                    pass
                if args.once:
                    return 1
                ser = open_port(args.port, args.baud)
                continue

            if not lines:
                print("papan diam - konsol tidak menjawab `s`")
            else:
                st = parse_status(lines)
                payload = {
                    "id": args.device,
                    "sector": args.sector,
                    # Posisi dari GPS dipakai begitu ada kunci; sebelum itu
                    # jatuh ke koordinat yang didaftarkan lewat argumen, supaya
                    # penanda di peta tidak melompat ke laut lepas (0,0).
                    "volt": st.get("volt", 0.0),
                    "current": st.get("current", 0.0),
                    "power": st.get("power", 0.0),
                    "dim": st.get("dim", 0),
                    "uptime": int(time.time() - started),
                }
                # Bidang tambahan ikut dikirim: backend mengabaikan yang tidak
                # dikenalnya, tapi datanya terlihat di broker saat menelusuri.
                for k in ("pf", "va", "temp_c", "humidity", "ldr_raw", "ldr_pct",
                          "tilt_deg", "relay", "auto", "rtc", "mains_note",
                          "gps_fix", "gps_sats", "gps_view", "alt_m"):
                    if k in st:
                        payload[k] = st[k]

                # Urutan kepercayaan: kunci GPS sekarang, lalu letak yang
                # tersimpan di flash papan, baru paksaan dari baris perintah.
                # Kalau tidak satu pun ada, lat/lng TIDAK dikirim sama sekali -
                # lebih baik backend mempertahankan posisi terdaftar daripada
                # menerima tebakan.
                lat = st.get("lat", st.get("site_lat", args.lat))
                lng = st.get("lng", st.get("site_lng", args.lng))
                if lat is not None and lng is not None:
                    payload["lat"] = lat
                    payload["lng"] = lng

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
