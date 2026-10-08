"""
Logika health status & evaluasi alert. Aturan dan urutan pengecekan disamakan
persis dengan node "Parse & Generate SQL Query" (health) dan
"Evaluasi & Build Query Alert" (threshold) di node-red-flow-acw.json.
"""
import config


def classify_health(uptime_hours: float) -> str:
    if uptime_hours >= config.UPTIME_NEED_MAINTENANCE_HOURS:
        return "Need Maintenance"
    if uptime_hours >= config.UPTIME_WARNING_HOURS:
        return "Warning"
    return "Healthy"


def evaluate_alert(device_id: str, volt: float, current: float,
                   volt_reported: bool = False):
    """
    Cek 3 aturan berurutan, cuma satu yang bisa terpicu per pesan (persis if/else-if
    di flow lama) — bukan cek semua aturan independen kayak _checkAndTriggerAlert()
    di frontend, itu logika deteksi anomali terpisah dan tidak diubah di sini.

    Return dict alert kalau ada yang terpicu, None kalau normal.
    """
    if volt > config.VOLT_SPIKE_THRESHOLD:
        return {
            "level": "Critical",
            "title": "Lonjakan Tegangan",
            "alertType": "voltage_spike",
            "message": (
                f"Lampu {device_id} terdeteksi lonjakan tegangan sebesar {volt}V, "
                f"melebihi batas aman {config.VOLT_SPIKE_THRESHOLD}V."
            ),
            "threshold_info": f"V: {config.VOLT_SPIKE_THRESHOLD}V",
        }

    # Nol dulu dikecualikan lewat "0 < volt", sehingga justru kasus paling jelas -
    # lampu terlepas, jala listrik hilang - tidak memicu apa pun. Pengecualian itu
    # ada alasannya: payload yang sama sekali tidak membawa medan "volt" juga dibaca
    # sebagai 0, dan itu bukan gangguan. Jadi yang dibedakan sekarang bukan angkanya,
    # melainkan apakah angkanya memang dilaporkan.
    if volt < config.VOLT_OFFLINE_THRESHOLD and (volt > 0 or volt_reported):
        no_power = volt <= 0
        return {
            "level": "Critical",
            "title": "Tanpa Tegangan Jala" if no_power else "Perangkat Offline / Tegangan Low",
            "alertType": "offline",
            "message": (
                f"Lampu {device_id} tidak mendapat tegangan jala sama sekali (0V) - "
                f"periksa sambungan atau pemutus arusnya."
                if no_power else
                f"Lampu {device_id} terdeteksi tegangan jauh di bawah batas operasional ({volt}V)."
            ),
            "threshold_info": f"V: {config.VOLT_OFFLINE_THRESHOLD}V",
        }

    if current > config.CURRENT_SPIKE_THRESHOLD:
        return {
            "level": "Critical",
            "title": "Lonjakan Arus",
            "alertType": "current_spike",
            "message": (
                f"Lampu {device_id} mendeteksi lonjakan arus listrik sebesar {current}A."
            ),
            "threshold_info": f"I: {config.CURRENT_SPIKE_THRESHOLD}A",
        }

    return None


def repeated_login_failure_alert(username: str, consecutive_count: int, client_ip: str) -> dict:
    """Alert saat satu username gagal login BERTURUT-TURUT (dihitung
    auth.record_login_failure(), direset begitu username itu berhasil login - lihat
    routes_auth.py). Dipicu tiap kelipatan 3 (3, 6, 9, ...) oleh pemanggil, bukan cuma
    sekali di kegagalan ke-3, supaya admin yang online tetap dapat sinyal kalau
    percobaannya terus berlanjut.

    username & client_ip DUA-DUANYA data dari luar tanpa autentikasi (body request
    login yang gagal) - message ini disimpan permanen ke tabel alerts lalu disiarkan
    ke semua dashboard, PERSIS jalur yang jadi celah XSS device_id dulu (commit
    01e8a3b). Aman di sini karena frontend escapeHtml() semua alert.message tanpa
    kecuali (lihat _buildAlertCardHTML di script.js) - tapi LoginRequest di
    routes_auth.py tetap dikasih max_length sebagai gerbang sumber juga, konsisten
    dengan pola dua-lapis yang sama."""
    return {
        "level": "Critical",
        "title": "Percobaan Login Gagal Berulang",
        "alertType": "repeated_login_failure",
        "message": (
            f"{consecutive_count} percobaan login berturut-turut gagal untuk akun "
            f"'{username}' dari IP {client_ip}. Kalau ini bukan kamu yang mencoba, "
            f"pertimbangkan ganti password."
        ),
        "threshold_info": f"{consecutive_count}x berturut-turut",
    }


def unknown_device_alert(device_id: str) -> dict:
    """Alert saat telemetry ditolak karena device_id belum diinput manual ke tabel
    devices - lihat mqtt_ingest.py._handle_telemetry(). Level Critical: data dari
    ID tak terdaftar dianggap upaya perangkat asing, bukan sekadar gangguan hardware."""
    return {
        "level": "Critical",
        "title": "Perangkat Tidak Terdaftar",
        "alertType": "unregistered_device",
        "message": (
            f"Data telemetry dari device_id '{device_id}' ditolak - ID ini belum "
            f"terdaftar di tabel devices. Kemungkinan perangkat asing mencoba mengirim data."
        ),
        "threshold_info": f"device_id: {device_id}",
    }
