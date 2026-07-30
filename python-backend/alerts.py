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


def evaluate_alert(device_id: str, volt: float, current: float):
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

    if 0 < volt < config.VOLT_OFFLINE_THRESHOLD:
        return {
            "level": "Critical",
            "title": "Perangkat Offline / Tegangan Low",
            "alertType": "offline",
            "message": (
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
