"""Periksa apakah papan NEMA benar-benar nyambung, dan ukur berapa lama ia menjawab.

Kenapa alat ini perlu
---------------------
Papan TIDAK pernah menyambung ke backend. Keduanya menyambung ke broker MQTT,
dan broker yang meneruskan - jadi "NEMA konek ke backend atau tidak" sebenarnya
dua pertanyaan yang berbeda, dan keduanya bisa gagal sendiri-sendiri:

    papan  --(telemetri)-->  broker  --(telemetri)-->  backend --> dashboard
    papan  <--(perintah)---  broker  <--(perintah)---  backend <-- dashboard

Dashboard yang menampilkan angka terbaru hanya membuktikan arah PERTAMA jalan.
Arah kedua - perintah sampai ke papan - tidak terbukti oleh apa pun yang
terlihat di layar, dan itulah arah yang gagal diam-diam.

Alat ini menguji keduanya, dengan ukuran waktu:

  1. Berapa lama sampai telemetri berikutnya datang  -> arah naik hidup?
  2. Kirim perintah yang TIDAK mengubah apa pun, lalu hitung berapa lama
     telemetri balasannya datang                     -> arah turun hidup?

Langkah 2 bisa begitu karena papan selalu melaporkan keadaannya segera setiap
kali menerima perintah yang ia pahami. Perintah yang dikirim adalah keadaan
relai papan SAAT INI, dibaca dari telemetri di langkah 1 - jadi ia sampai ke
papan, diterapkan, dan tidak mengubah apa pun. Lampu tidak berkedip.

Pakai:
    python cek_nema.py                      # broker & perangkat bawaan
    python cek_nema.py --device NEMA-01
    python cek_nema.py --broker broker.hivemq.com --timeout 90
"""
import argparse
import json
import sys
import threading
import time

import paho.mqtt.client as mqtt

BROKER_BAWAAN = "broker.hivemq.com"
PORT_BAWAAN = 1883


def main() -> int:
    ap = argparse.ArgumentParser(description="Periksa sambungan papan NEMA lewat broker MQTT.")
    ap.add_argument("--broker", default=BROKER_BAWAAN)
    ap.add_argument("--port", type=int, default=PORT_BAWAAN)
    ap.add_argument("--device", default="NEMA-01")
    ap.add_argument("--timeout", type=float, default=90.0,
                    help="batas tunggu telemetri, detik (bawaan 90 - periode normalnya 60)")
    args = ap.parse_args()

    topik_telemetri = f"iot/lights/{args.device}/telemetry"
    topik_perintah = f"iot/lights/{args.device}/command"

    telemetri: list[tuple[float, dict]] = []
    tersimpan: list[bytes] = []
    datang = threading.Event()

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            return
        client.subscribe(topik_telemetri, 1)
        client.subscribe(topik_perintah, 1)

    def on_message(client, userdata, msg):
        if msg.topic == topik_perintah:
            # retain=1 berarti ini pesan TERSIMPAN, bukan perintah yang baru terbit
            if msg.retain and msg.payload:
                tersimpan.append(msg.payload)
            return
        try:
            telemetri.append((time.time(), json.loads(msg.payload.decode("utf-8", "replace"))))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        datang.set()

    c = mqtt.Client(client_id="cek-nema-%d" % (time.time() * 1000 % 1000000))
    c.on_connect = on_connect
    c.on_message = on_message

    print(f"Broker    {args.broker}:{args.port}")
    print(f"Perangkat {args.device}")
    print()

    try:
        c.connect(args.broker, args.port, 30)
    except OSError as e:
        print(f"[X] Broker tidak bisa dihubungi dari PC ini: {e}")
        print("    Berarti PC-mu yang terputus, belum tentu papannya.")
        return 1
    c.loop_start()

    # --- 1. arah naik: papan -> broker ---------------------------------------
    print(f"[1] Menunggu telemetri (batas {args.timeout:.0f} detik)...")
    mulai = time.time()
    if not datang.wait(args.timeout):
        print(f"[X] TIDAK ADA telemetri dalam {args.timeout:.0f} detik.")
        print("    Papan tidak terhubung ke broker: modem sedang mencari jaringan,")
        print("    papan mati, atau sesi MQTT-nya putus dan sedang dibangun ulang.")
        print("    Periksa LED modem di papan sebelum menyalahkan backend.")
        c.loop_stop()
        c.disconnect()
        return 1

    tunggu = time.time() - mulai
    _, isi = telemetri[-1]
    relai = str(isi.get("relay", "")).lower()
    print(f"[ok] Telemetri datang setelah {tunggu:.1f} detik - arah NAIK hidup.")
    print(f"     dim {isi.get('dim')} %   relay {relai}   auto {isi.get('auto')}   "
          f"volt {isi.get('volt')}   power {isi.get('power')}")
    print()

    if relai not in ("on", "off"):
        print("[X] Telemetri tidak menyebut keadaan relai, uji arah turun dilewati.")
        c.loop_stop()
        c.disconnect()
        return 1

    # --- 2. arah turun: broker -> papan --------------------------------------
    # Perintahnya adalah keadaan relai papan SAAT INI: sampai, diterapkan, tidak
    # mengubah apa pun. retain=False supaya tidak meninggalkan perintah tersimpan.
    print(f"[2] Mengirim perintah uji {{\"relay\": \"{relai}\"}} - sama dengan keadaan sekarang,")
    print("    jadi lampu tidak berubah. Papan selalu melapor segera setelah menerima perintah.")
    datang.clear()
    jumlah_sebelum = len(telemetri)
    t_kirim = time.time()
    c.publish(topik_perintah, json.dumps({"relay": relai}), qos=1, retain=False)

    # Batas 25 detik: balasan perintah datang dalam hitungan detik kalau papan
    # mendengar. Lebih lama dari itu dan yang datang kemungkinan besar telemetri
    # berkala biasa, bukan balasan - jadi tidak membuktikan apa-apa.
    if not datang.wait(25.0):
        print("[X] Papan TIDAK menjawab dalam 25 detik.")
        print("    Arah NAIK hidup tapi arah TURUN tidak: papan menerbitkan telemetri")
        print("    namun perintah tidak sampai padanya. Lihat apakah langganan topik")
        print("    perintahnya berhasil (+QMTSUB) di konsol papan.")
        c.loop_stop()
        c.disconnect()
        return 1

    balas = time.time() - t_kirim
    _, isi2 = telemetri[-1]
    print(f"[ok] Papan menjawab dalam {balas:.1f} detik - arah TURUN hidup.")
    print(f"     dim {isi2.get('dim')} %   relay {isi2.get('relay')}   auto {isi2.get('auto')}")
    print(f"     ({len(telemetri) - jumlah_sebelum} telemetri masuk sejak perintah dikirim)")
    print()

    # --- 3. perintah tersimpan yang mungkin masih menggantung ----------------
    if tersimpan:
        print(f"[!] Ada perintah TERSIMPAN di broker: {tersimpan[-1].decode('utf-8', 'replace')}")
        print("    Papan yang baru menyala akan menerimanya. Umurnya dibatasi 5 menit")
        print("    oleh backend (RETAINED_COMMAND_TTL_SECONDS), jadi ini normal kalau")
        print("    kamu baru saja menekan tombol di dashboard.")
    else:
        print("[ok] Tidak ada perintah tersimpan yang menggantung di broker.")

    print()
    print("Kesimpulan: dua arah jalan. Kalau dashboard tetap terasa tidak menjawab,")
    print("masalahnya ada di antara dashboard dan broker - periksa backend dengan")
    print("cek-sistem-windows.bat, bukan papannya.")

    c.loop_stop()
    c.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
