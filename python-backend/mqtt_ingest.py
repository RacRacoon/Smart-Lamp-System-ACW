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
import threading
import time
import uuid

import paho.mqtt.client as mqtt

import alerts
import config
import db
import ws_manager

logger = logging.getLogger("acw.mqtt")

# Kapan tiap (device_id, jenis alert) terakhir dicatat. Di memori saja: hilang
# saat backend dinyalakan ulang, dan itu justru yang diinginkan - setelah
# restart, gangguan yang masih berlangsung layak dilaporkan sekali lagi.
_alert_seen: dict[tuple[str, str], float] = {}

# Penghapus perintah tersimpan, satu per perangkat.
#
# Perintah diterbitkan dengan retain=True supaya tidak hilang saat perangkat
# sedang menyambung ulang - itu tetap perlu. Tapi "tersimpan" di MQTT berarti
# SELAMANYA: lampu yang dimatikan dari dashboard malam ini akan menerima
# perintah mati itu lagi setiap kali ia menyala, berminggu-minggu kemudian,
# dan dari luar terlihat seperti perangkat yang menolak bekerja.
#
# Protokolnya sendiri tidak punya kedaluwarsa, dan pesan tersimpan tidak
# membawa stempel waktu - perangkat tak punya cara menilai umurnya. Jadi yang
# menghapus adalah pihak yang tahu kapan ia menerbitkan: backend ini.
_retain_timers: dict[str, threading.Timer] = {}


def _alert_due(device_id: str, alert_type: str) -> bool:
    """1 kalau alert sejenis dari lampu ini sudah boleh dicatat lagi."""
    key = (device_id, alert_type)
    now = time.monotonic()
    last = _alert_seen.get(key)
    if last is not None and (now - last) < config.ALERT_COOLDOWN_SECONDS:
        return False
    _alert_seen[key] = now
    return True


def _parse_payload(topic: str, raw: dict) -> dict:
    topic_parts = topic.split("/")
    device_id = raw.get("id") or raw.get("device_id") or (topic_parts[2] if len(topic_parts) > 2 else "UNKNOWN")

    sector = raw.get("sector") or config.DEFAULT_SECTOR
    # Dibedakan dari "tidak dikirim": lihat alerts.evaluate_alert().
    volt_reported = raw.get("volt") is not None

    # None kalau perangkat tidak melaporkannya, BUKAN sebuah angka bawaan.
    # Menambal dengan konstanta global berarti lampu yang kebetulan tidak
    # mengirim posisi akan tertarik ke titik yang sama di peta, menimpa
    # koordinat yang didaftarkan admin - kesalahan yang terlihat meyakinkan
    # karena penandanya tetap muncul, hanya saja di tempat yang salah.
    lat = float(raw["lat"]) if raw.get("lat") is not None else None
    lng = float(raw["lng"]) if raw.get("lng") is not None else None
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

    # Lampu dianggap menyala kalau peredupnya di atas nol DAN relainya tidak
    # dilaporkan padam. Perangkat yang tidak mengirim "relay" cukup dinilai dari
    # dim saja - itu yang menentukan apakah lampu benar-benar menua.
    lamp_on = dim > 0 and str(raw.get("relay", "on")).lower() != "off"

    # Keadaan yang DIAKUI papan di telemetri ini - dasar posisi saklar di
    # dashboard. None berarti papan tidak melaporkannya, bukan "mati": kolomnya
    # tidak boleh ditimpa oleh tebakan, karena nilai lama masih lebih benar
    # daripada nilai karangan.
    relay_on = None if raw.get("relay") is None else str(raw["relay"]).lower() != "off"
    auto_mode = None if raw.get("auto") is None else bool(raw["auto"])

    return {
        "device_id": device_id,
        "sector": sector,
        "lat": lat,
        "lng": lng,
        "volt": volt,
        "current": current,
        "power": power,
        "uptime_hours": uptime_hours,
        "lamp_on": lamp_on,
        "volt_reported": volt_reported,
        "dim": dim,
        "relay_on": relay_on,
        "auto_mode": auto_mode,
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

    # Usia pakai diambil dari database, BUKAN dari yang dikirim perangkat. Field
    # "uptime" di payload ikut ter-reset tiap pengirimnya dinyalakan ulang, dan
    # indikator umur lampu tidak boleh punya sifat itu.
    try:
        data["uptime_hours"] = round(db.accrue_lamp_hours(device_id, data["lamp_on"]), 2)
    except Exception:
        logger.exception("Gagal memperbarui usia pakai lampu untuk %s", device_id)

    # Keadaan papan disimpan supaya bertahan melewati muat ulang dashboard,
    # restart backend, dan login baru. Sebelum ini tidak ada yang menyimpannya:
    # saklar relai & auto selalu kembali ke posisi MATI tiap halaman dibuka,
    # apa pun yang sedang terjadi pada lampu sebenarnya.
    try:
        db.save_reported_state(device_id, data["relay_on"], data["auto_mode"])
    except Exception:
        logger.exception("Gagal menyimpan keadaan relai/auto untuk %s", device_id)

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
        "dim": data["dim"],
        # Saklar di dashboard mengikuti pengakuan papan. Kunci ini sengaja
        # dihilangkan kalau papan tidak melaporkannya - dashboard membedakan
        # "tidak dilaporkan" dari "mati" lewat undefined (lihat switchDevice).
        **({"relay": "on" if data["relay_on"] else "off"}
           if data["relay_on"] is not None else {}),
        **({"auto": data["auto_mode"]} if data["auto_mode"] is not None else {}),
        # Posisi hanya ikut kalau memang dilaporkan. Tanpa kunci ini, dashboard
        # menerima lat/lng kosong lalu menggambar penanda di koordinat nol.
        **({"lat": data["lat"], "lng": data["lng"]}
           if data["lat"] is not None and data["lng"] is not None else {}),
    })

    alert = alerts.evaluate_alert(device_id, data["volt"], data["current"],
                                  data["volt_reported"])
    if not alert:
        return

    # Gangguan yang bertahan hanya dicatat sekali per jeda, bukan tiap telemetri.
    if not _alert_due(device_id, alert["alertType"]):
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
        # Sebut broker-nya terang-terangan. MQTT_HOST default di config.py itu
        # broker.emqx.io yang publik, jadi backend yang lupa diberi env var tetap
        # menyala mulus, tetap bilang "terhubung", dan diam-diam menerbitkan
        # perintah ke broker orang lain - perangkat tidak pernah menerimanya.
        # Sudah kejadian: dua backend jalan bareng, yang menjawab localhost justru
        # yang salah broker, dan gejalanya terbaca seperti NEMA yang membandel.
        logger.info("Terhubung ke broker MQTT %s:%s, subscribe topic %s",
                    config.MQTT_HOST, config.MQTT_PORT, config.MQTT_TELEMETRY_TOPIC)

        # Dilakukan di sini, bukan di start(): menerbitkan sesuatu hanya mungkin
        # setelah benar-benar tersambung. Ikut jalan di tiap sambungan ulang,
        # dan itu memang yang diinginkan - sambungan yang putus lama juga
        # meninggalkan perintah tersimpan yang umurnya tidak lagi diketahui.
        _clear_orphan_retained_commands()
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
    """Mulai network loop MQTT di thread background. TIDAK menunggu sambungan.

    Dulu di sini dipakai client.connect(), yang menyambung secara sinkron dan
    MELEMPAR kalau broker tidak terjangkau. Karena fungsi ini dipanggil dari
    event startup FastAPI, lemparan itu menjatuhkan seluruh proses:
    "Application startup failed. Exiting." Satu broker yang mati membuat
    dashboard, riwayat telemetri, kotak peringatan, login - semuanya -
    ikut tidak bisa dibuka, padahal semua itu ada di Postgres dan sama sekali
    tidak butuh MQTT. Terjadi 21 Okt 2026: server broker turun, dan yang
    terlihat oleh pengguna adalah "backend error".

    connect_async() menyerahkan penyambungan ke loop background, yang juga
    mengulang sendiri dengan jeda menanjak. Jadi backend selalu menyala, dan
    begitu broker kembali ia menyambung tanpa perlu direstart. Keadaan
    sambungannya tidak disembunyikan - /health melaporkannya (dan menjawab
    503), jadi yang hilang cuma matinya, bukan kabarnya.
    """
    global _client
    # Suffix acak per proses - client_id tetap pernah ketabrak sesama instance (restart lama
    # belum lepas, atau dua instance jalan bareng) dan broker.emqx.io menolak terus (CONNACK
    # rc=5, "not authorised") sampai id-nya diganti. Sudah dibuktikan langsung waktu tes.
    client_id = f"{config.MQTT_CLIENT_ID}_{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(client_id=client_id, clean_session=True)
    client.on_connect = _on_connect
    client.on_message = _on_message

    # Jeda ulang menanjak: 1 detik di percobaan pertama sampai 60 detik. Rapat
    # di awal supaya gangguan sekejap nyaris tak terasa, melebar sesudahnya
    # supaya broker yang mati berjam-jam tidak dihujani percobaan sambung.
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    client.loop_start()
    _client = client
    logger.info("Loop MQTT dimulai, menyambung ke %s:%s di latar belakang",
                config.MQTT_HOST, config.MQTT_PORT)
    return client


def status() -> dict:
    """Keadaan sambungan MQTT, buat endpoint /health.

    Broker-nya ikut disebut, bukan cuma "tersambung atau tidak". Backend yang
    tersambung ke broker SALAH tetap menjawab "tersambung" dengan jujur, dan
    itulah bentuk kegagalan yang paling sulit dilihat: semua tampak sehat,
    perintah terbit tanpa error, papan tidak pernah menerimanya.
    """
    return {
        "connected": bool(_client is not None and _client.is_connected()),
        "broker": f"{config.MQTT_HOST}:{config.MQTT_PORT}",
    }


def _clear_retained_command(device_id: str, alasan: str | None = None) -> None:
    """Hapus perintah tersimpan: muatan kosong, retain tetap True.

    Broker membacanya sebagai perintah hapus, bukan pesan baru - pelanggan
    berikutnya tidak menerima apa pun saat berlangganan.

    Dipanggil dari dua jalur: timer TTL yang jatuh tempo, dan pembersihan
    pesan yatim saat tersambung. Alasannya ikut dicatat supaya keduanya bisa
    dibedakan di log.
    """
    _retain_timers.pop(device_id, None)
    if _client is None:
        return
    try:
        topic = config.MQTT_COMMAND_TOPIC_TEMPLATE.format(device_id=device_id)
        _client.publish(topic, payload=b"", qos=1, retain=True)
        logger.info("Perintah tersimpan untuk %s dihapus (%s)", device_id,
                    alasan or "umur %d detik terlampaui" % config.RETAINED_COMMAND_TTL_SECONDS)
    except Exception:
        logger.exception("Gagal menghapus perintah tersimpan untuk %s", device_id)


def _clear_orphan_retained_commands() -> None:
    """Hapus perintah tersimpan yang tidak dijaga timer proses ini.

    Umur perintah tersimpan dijaga oleh timer di MEMORI proses ini, dan itu
    punya satu lubang: backend yang berhenti - restart, mati listrik, ganti
    kode - membawa timernya mati bersamanya, sementara pesan tersimpannya
    tetap hidup di broker SELAMANYA. Tidak ada lagi yang berniat
    menghapusnya, dan tiap kali papan tersambung ulang broker mengirimkannya
    lagi. Satu {"relay": "off"} yang tertinggal berarti lampu dipaksa padam
    setiap kali ia kembali - persis bencana yang TTL ini dibuat untuk
    mencegah. Terbukti terjadi 13 Okt 2026, setelah restart backend biasa.

    Protokolnya tidak memberi stempel waktu pada pesan tersimpan, jadi umur
    pesan yang kita temukan di broker TIDAK BISA diketahui. Satu-satunya
    bacaan yang aman adalah "kedaluwarsa": perintah dari masa lalu yang tak
    bertuan lebih berbahaya daripada perintah yang hilang, karena yang hilang
    terlihat - dashboard tetap menampilkan keadaan papan yang sebenarnya.

    Perangkat yang masih punya timer hidup DILEWATI: perintahnya baru saja
    diterbitkan oleh proses ini, umurnya diketahui, dan masih berhak sampai
    ke papan yang sedang menyambung ulang.
    """
    try:
        device_ids = db.get_all_device_ids()
    except Exception:
        logger.exception("Gagal membaca daftar perangkat untuk membersihkan perintah yatim")
        return

    for device_id in device_ids:
        if device_id in _retain_timers:
            continue
        _clear_retained_command(device_id, alasan="yatim, tidak ada timer yang menjaganya")


def publish_control_command(device_id: str, payload: dict) -> None:
    """Terbitkan satu perintah kendali ke topic command sebuah device.

    Isinya bebas - {"dim": 60}, {"auto": true}, atau keduanya - dan hanya field
    yang memang diminta yang ikut, supaya perintah mode otomatis tidak
    membawa-bawa kecerahan yang tidak dimaksud.
    """
    if not config.is_valid_device_id(device_id):
        raise ValueError(f"device_id tidak valid buat topic MQTT: {device_id!r}")
    if _client is None:
        raise RuntimeError("MQTT belum konek, panggil start() dulu")
    topic = config.MQTT_COMMAND_TOPIC_TEMPLATE.format(device_id=device_id)

    # retain=True, dan ini bukan pilihan gaya. Perangkat di jaringan seluler
    # putus-sambung terus; perintah yang kebetulan terbit saat ia sedang
    # menyambung ulang akan hilang tanpa jejak - operator menggeser slider,
    # tidak terjadi apa-apa, dan tidak ada yang memberi tahu kenapa.
    #
    # Dengan retained, broker menyimpan perintah TERAKHIR dan mengirimkannya
    # begitu perangkat berlangganan lagi. Yang disimpan jadi "keadaan yang
    # diinginkan", bukan "kejadian sesaat" - dan untuk kecerahan serta mode
    # otomatis, itu memang artinya.
    info = _client.publish(topic, json.dumps(payload), qos=1, retain=True)

    # Hasilnya DIPERIKSA. Tanpa ini, perintah yang diterbitkan selagi MQTT
    # terputus tetap membuat endpoint menjawab 200: dashboard melapor
    # "terkirim", operator menunggu, dan tidak ada apa pun yang memberi tahu
    # bahwa perintah itu tidak pernah meninggalkan proses ini.
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(
            "perintah gagal diterbitkan ke broker %s:%s (kode %s) - "
            "sambungan MQTT sedang terputus"
            % (config.MQTT_HOST, config.MQTT_PORT, info.rc)
        )

    # Jadwalkan penghapusannya. Perintah berikutnya membatalkan jadwal lama dan
    # memulai hitungan baru, jadi yang berlaku selalu umur perintah TERAKHIR.
    old = _retain_timers.pop(device_id, None)
    if old is not None:
        old.cancel()
    t = threading.Timer(config.RETAINED_COMMAND_TTL_SECONDS,
                        _clear_retained_command, args=(device_id,))
    t.daemon = True          # jangan menahan proses saat backend dihentikan
    t.start()
    _retain_timers[device_id] = t


def publish_dim_command(device_id: str, dim: int) -> None:
    """Setara dengan node mqtt-out "Publish to MQTT" (POST /api/lights/:id/command).
    Pakai koneksi MQTT yang sama dengan subscriber telemetry, tidak buka koneksi baru."""
    if not config.is_valid_device_id(device_id):
        # device_id masuk mentah ke topic MQTT di bawah - kalau berisi "/", topic
        # publish-nya BERUBAH (mis. device_id="a/../b" bikin topic keluar dari
        # "iot/lights/X/command" yang dimaksud). Broker (broker.emqx.io) publik tanpa
        # auth/namespace, jadi topic sembarangan bisa nyenggol pihak lain yang juga
        # pakai broker itu. Endpoint pemanggil (routes_command.py) sudah cek ini duluan
        # buat kasih pesan error yang jelas ke admin - baris ini gerbang kedua/terakhir.
        raise ValueError(f"device_id tidak valid buat topic MQTT: {device_id!r}")
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
    if not config.is_valid_device_id(device_id):
        # Sama alasannya dengan publish_dim_command() - device_id di sini datang dari
        # db.get_device_ids_by_sector() (routes_schedules.py), harusnya sudah lolos
        # gerbang provisioning, tapi tetap dicek ulang di sini sebagai jaring terakhir
        # sebelum jadi topic MQTT. Exception ini ketangkep except Exception di pemanggil
        # (satu device_id aneh tidak menggagalkan publish ke device lain di sektor sama).
        raise ValueError(f"device_id tidak valid buat topic MQTT: {device_id!r}")
    if _client is None:
        raise RuntimeError("MQTT belum konek, panggil start() dulu")
    topic = config.MQTT_COMMAND_TOPIC_TEMPLATE.format(device_id=device_id)
    payload = json.dumps({"schedule": phases})
    _client.publish(topic, payload, qos=1, retain=True)
