// Backend Python (python-backend/) - satu proses REST+WebSocket. Diturunkan dari host
// halaman ini sendiri (location.hostname), BUKAN hardcode "localhost" - kalau di-hardcode,
// dashboard yang dibuka dari HP bakal manggil "localhost:8000" milik HP itu sendiri
// (bukan PC server), jadi semua fetch/WS gagal diam-diam dan dashboard tampak kosong.
const API_BASE_URL = `http://${location.hostname}:8000`;
const TELEMETRY_WS_URL = `ws://${location.hostname}:8000/ws/telemetry`;
let socket;

// Samakan default font/warna Chart.js dengan tema dasbor (Inter + abu-abu muted) -
// tidak mengubah warna per-dataset yang sudah diset manual di drawChart().
if (typeof Chart !== 'undefined') {
    Chart.defaults.font.family = "'Inter', 'Segoe UI', sans-serif";
    Chart.defaults.color = '#8a99ad';
}

function connectWebSocket() {
    socket = new WebSocket(TELEMETRY_WS_URL);

    socket.onopen = function (event) {
        console.log("Terhubung ke backend secara Real-Time!");
        setConnectionStatus(true);
    };

    socket.onmessage = function (event) {
        try {
            const incomingData = JSON.parse(event.data);
            const deviceId = incomingData.id;

            if (deviceId) {
                // KUNCI DINAMIS: Jika ID lampu baru (seperti L-107) belum terdaftar di JS
                if (!devicesData[deviceId]) {
                    console.log(`Mendeteksi node baru dari backend: ${deviceId}`);

                    // 1. Buat data default di JS lokal, satukan dengan koordinat dari Node-RED
                    devicesData[deviceId] = {
                        id: deviceId,
                        sector: incomingData.sector || "Sektor Tidak Diketahui",
                        health: incomingData.health || "Healthy",
                        power: incomingData.power || 0,
                        volt: incomingData.volt || 0,
                        current: incomingData.current || 0,
                        lat: incomingData.lat || -7.25000, // Koordinat default jika dari backend kosong
                        lng: incomingData.lng || 112.75000,
                        alerts: incomingData.alerts || 0,
                        uptime: incomingData.uptime || 0,
                        dim: incomingData.dim !== undefined ? parseInt(incomingData.dim) : 8
                    };

                    // Inisialisasi telemetryHistory default untuk node baru ini
                    if (!telemetryHistory[deviceId]) {
                        telemetryHistory[deviceId] = {
                            labels: ["02:00", "04:00", "06:00", "08:00", "10:00", "12:00", "14:00"],
                            volt: Array(7).fill(incomingData.volt || 0),
                            ampere: Array(7).fill(incomingData.current || 0),
                            watt: Array(7).fill(incomingData.power || 0)
                        };
                    }

                    // 2. Suntik opsi secara dinamis ke semua Dropdown HTML (Dashboard, Manage, Telemetry)
                    addDeviceToDropdowns(deviceId, devicesData[deviceId].sector);

                    // 3. Gambar Pinpoint Lampu Baru secara otomatis ke peta MapLibre
                    addNewMapMarker(devicesData[deviceId]);
                } else {
                    // Jika sudah ada, tinggal perbarui datanya secara real-time
                    devicesData[deviceId] = {
                        ...devicesData[deviceId],
                        ...incomingData
                    };
                }

                // PERBAIKAN (di dalam socket.onmessage)
                const activeSector = incomingData.sector || "Sektor Tidak Diketahui";
                if (!sectorSettings[activeSector]) {
                    sectorSettings[activeSector] = {
                        schedules: incomingData.schedules || [
                            { time: "17:30", dim: 6, cct: 30 },
                            { time: "23:00", dim: 4, cct: 80 },
                            { time: "03:30", dim: 8, cct: 100 }
                        ]
                    };
                }

                // === UPDATE REAL-TIME TELEMETRY HISTORY & CHART ===
                if (telemetryHistory[deviceId]) {
                    const timeNow = new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });

                    // Pastikan array-array target ada untuk mencegah crash
                    if (!telemetryHistory[deviceId].labels) telemetryHistory[deviceId].labels = [];
                    if (!telemetryHistory[deviceId].volt) telemetryHistory[deviceId].volt = [];

                    // Buat alias ke key data telemetryHistory untuk kompatibilitas PZEM
                    if (!telemetryHistory[deviceId].ampere) {
                        telemetryHistory[deviceId].ampere = [...(telemetryHistory[deviceId].current || [])];
                    }
                    if (!telemetryHistory[deviceId].watt) {
                        telemetryHistory[deviceId].watt = [...(telemetryHistory[deviceId].power || [])];
                    }

                    // Tambahkan titik data telemetry terbaru
                    telemetryHistory[deviceId].labels.push(timeNow);
                    telemetryHistory[deviceId].volt.push(incomingData.volt !== undefined ? incomingData.volt : (devicesData[deviceId].volt || 0));
                    telemetryHistory[deviceId].ampere.push(incomingData.current !== undefined ? incomingData.current : (devicesData[deviceId].current || 0));
                    telemetryHistory[deviceId].watt.push(incomingData.power !== undefined ? incomingData.power : (devicesData[deviceId].power || 0));

                    // Jika objek juga menggunakan key .current dan .power, amankan agar ukurannya tetap sejajar
                    if (telemetryHistory[deviceId].current) telemetryHistory[deviceId].current.push(incomingData.current || 0);
                    if (telemetryHistory[deviceId].power) telemetryHistory[deviceId].power.push(incomingData.power || 0);

                    // === BATASI MAKSIMAL 20 DATA POIN PADA GRAFIK ===
                    const MAX_POINTS = 100; // Sesuaikan dengan LIMIT di query Node-RED kamu
                    if (telemetryHistory[deviceId].labels.length > MAX_POINTS) {
                        telemetryHistory[deviceId].labels.shift();
                        telemetryHistory[deviceId].volt.shift();
                        telemetryHistory[deviceId].ampere.shift();
                        telemetryHistory[deviceId].watt.shift();
                        if (telemetryHistory[deviceId].current) telemetryHistory[deviceId].current.shift();
                        if (telemetryHistory[deviceId].power) telemetryHistory[deviceId].power.shift();
                    }

                    // Jika lampu ini termasuk sektor yang sedang dibuka di tab Riwayat Data,
                    // perbarui grafik miliknya saja secara instant (tiap lampu punya chart sendiri)
                    if (devicesData[deviceId].sector === currentTelemetrySector && document.getElementById(`telemetryChart-${deviceId}`)) {
                        drawChart(deviceId);
                        updateTelemetrySummary(deviceId);
                    }
                }

                // Jalankan sinkronisasi halaman jika perangkat ini sedang aktif dibuka
                const currentActiveDevice = document.getElementById("current-device-id")?.innerText;
                if (currentActiveDevice === deviceId) {
                    switchDevice(deviceId); // Fungsi sinkronisasi multidimensi kita
                }

                // === DETEKSI ANOMALI & TRIGGER ALERT ===
                // Jika pesan dari Node-RED membawa flag alert eksplisit, proses langsung
                if (incomingData.alert === true) {
                    const alertSeverity = incomingData.severity ||
                        (incomingData.alertType === 'voltage_spike' || incomingData.alertType === 'current_spike' || incomingData.alertType === 'offline'
                            ? 'critical' : 'warning');
                    addAlert({
                        nodeId: deviceId,
                        severity: alertSeverity,
                        type: incomingData.alertType || 'unknown',
                        message: generateAlertMessage(incomingData.alertType || 'unknown', deviceId, incomingData.volt || 0, incomingData.current || 0),
                        volt: parseFloat(incomingData.volt) || 0,
                        current: parseFloat(incomingData.current) || 0,
                        power: parseFloat(incomingData.power) || 0,
                        threshold: {},
                        timestamp: new Date(),
                        isRead: false,
                        isDismissed: false
                    });
                } else {
                    // Deteksi otomatis berdasarkan nilai telemetri
                    _checkAndTriggerAlert(deviceId, devicesData[deviceId]);
                }
            } else if (incomingData.alert === true) {
                // Alert tanpa field "id" - device_id-nya sengaja TIDAK didaftarkan
                // sebagai node dashboard (misal: backend menolak data dari perangkat
                // asing yang belum terdaftar di database). Tampilkan alert-nya saja,
                // jangan sentuh devicesData/peta/dropdown sama sekali.
                addAlert({
                    nodeId: incomingData.device_id || 'UNKNOWN',
                    severity: incomingData.severity || 'critical',
                    type: incomingData.alertType || 'unknown',
                    message: incomingData.message || 'Terjadi peringatan tanpa detail dari backend.',
                    volt: 0,
                    current: 0,
                    power: 0,
                    threshold: {},
                    timestamp: new Date(),
                    isRead: false,
                    isDismissed: false
                });
            }
        } catch (error) {
            console.error("Gagal memproses data dinamis dari backend:", error);
        }
    };

    socket.onclose = function (event) {
        console.log("Koneksi ke backend terputus. Mencoba menghubungkan kembali dalam 5 detik...");
        setConnectionStatus(false);
        setTimeout(connectWebSocket, 5000);
    };

    socket.onerror = function (error) {
        console.error("WebSocket Error: ", error);
    };
}

// Perbarui indikator titik hijau/merah + teks status koneksi di footer sidebar
function setConnectionStatus(isOnline) {
    const statusEl = document.getElementById("connection-status");
    const textEl = document.getElementById("connection-status-text");
    if (!statusEl || !textEl) return;

    statusEl.classList.remove("is-online", "is-offline");
    statusEl.classList.add(isOnline ? "is-online" : "is-offline");
    textEl.textContent = isOnline ? "Terhubung" : "Menyambung ulang...";
}

function addDeviceToDropdowns(deviceId, sector) {
    const devSelector = document.getElementById("device-selector");
    const telSectorSelector = document.getElementById("telemetry-sector-selector");
    const sectorSelector = document.getElementById("sector-selector-input");

    const optionExists = (selectEl, value) => {
        if (!selectEl) return false;
        return Array.from(selectEl.options).some(opt => opt.value === value);
    };

    if (devSelector && !optionExists(devSelector, deviceId)) {
        const opt = document.createElement("option");
        opt.value = deviceId;
        // Hapus teks ' (Healthy)' di bawah ini
        opt.textContent = `Tiang ${deviceId}`;
        devSelector.appendChild(opt);
    }

    // Riwayat Data dikelompokkan per sektor (bukan per lampu lagi) - dropdown ini cuma
    // perlu didaftar sekali per sektor, isi lampunya di-generate oleh changeTelemetrySector().
    if (telSectorSelector && sector && !optionExists(telSectorSelector, sector)) {
        const opt = document.createElement("option");
        opt.value = sector;
        opt.textContent = sector;
        telSectorSelector.appendChild(opt);
    }

    // Kalau lampu baru ini masuk ke sektor yang sedang ditampilkan di halaman Riwayat Data,
    // render ulang daftarnya supaya lampu baru langsung muncul tanpa perlu ganti-ganti dropdown.
    if (sector === currentTelemetrySector && document.getElementById("page-telemetry").style.display !== "none") {
        renderTelemetrySectorList(sector);
    }

    if (sectorSelector && sector && !optionExists(sectorSelector, sector)) {
        const opt = document.createElement("option");
        opt.value = sector;
        opt.textContent = sector;
        sectorSelector.appendChild(opt);

        if (!sectorSettings[sector]) {
            sectorSettings[sector] = {
                schedules: [
                    { time: "17:30", dim: 6, cct: 30 },
                    { time: "23:00", dim: 4, cct: 80 },
                    { time: "03:30", dim: 8, cct: 100 }
                ]
            };
        }

        // Kalau sektor baru ini yang sedang dibuka di tab Kelola Lampu, render jadwalnya
        if (sector === currentManageSector && document.getElementById("page-manage").style.display !== "none") {
            renderSchedulePhases(sector);
        }
    }
}

function onMarkerClick(device) {
    if (!device) return;
    const deviceId = device.id;

    // Sinkronisasi dropdown pemilih lampu
    const selector = document.getElementById("device-selector");
    if (selector) selector.value = deviceId;

    // Update data perangkat, tampilkan panel detail, dan terbangkan peta secara smooth
    switchDevice(deviceId);
}

function addNewMapMarker(data) {
    if (!map) return;
    const key = data.id;
    if (markers[key]) return; // Marker already exists

    const el = document.createElement('div');
    el.className = 'custom-pinpoint';
    el.style.cursor = 'pointer';
    el.style.width = '32px';
    el.style.height = '32px';
    el.style.transition = 'transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)';

    el.innerHTML = `
        <svg viewBox="0 0 24 24" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
            <path class="pin-path" d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z" 
            fill="#94a3b8" stroke="#ffffff" stroke-width="1.5" style="transition: fill 0.3s ease;"/>
        </svg>
    `;

    const marker = new maplibregl.Marker({ element: el, anchor: 'bottom' })
        .setLngLat([data.lng, data.lat])
        .addTo(map);

    marker.getElement().addEventListener('click', () => {
        onMarkerClick(data);
    });

    markers[key] = marker;
}

// Jalankan inisialisasi aplikasi saat halaman web selesai dimuat (DOM Ready)
// ============================================================
//  AUTENTIKASI — Login, Peran (Role), Proteksi Halaman Admin
// ============================================================

let currentRole = null;
let authToken = null;
let dashboardInitialized = false;

function handleLogin(event) {
    event.preventDefault();
    const usernameInput = document.getElementById("login-username");
    const passwordInput = document.getElementById("login-password");
    const errorEl = document.getElementById("login-error");
    const submitBtn = event.target.querySelector(".btn-login");
    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    submitBtn.disabled = true;
    errorEl.style.display = "none";

    fetch(`${API_BASE_URL}/api/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
    })
        .then(res => {
            if (!res.ok) throw new Error('unauthorized');
            return res.json();
        })
        .then(data => {
            sessionStorage.setItem("acw_role", data.role);
            sessionStorage.setItem("acw_token", data.token);
            enterDashboard(data.role, data.token);
        })
        .catch(() => {
            errorEl.textContent = "Username atau kata sandi salah. Silakan coba lagi.";
            errorEl.style.display = "block";
            passwordInput.value = "";
            passwordInput.focus();
        })
        .finally(() => {
            submitBtn.disabled = false;
        });
}

function logout() {
    sessionStorage.removeItem("acw_role");
    sessionStorage.removeItem("acw_token");
    location.href = location.pathname; // reload bersih, hapus hash halaman terakhir
}

function enterDashboard(role, token) {
    currentRole = role;
    authToken = token;

    document.getElementById("login-overlay").style.display = "none";
    document.getElementById("app-shell").style.display = "flex";

    const roleBadge = document.getElementById("role-badge");
    if (roleBadge) roleBadge.textContent = role === "admin" ? "Admin" : "Petugas Monitoring";

    applyRoleRestrictions(role);

    if (!dashboardInitialized) {
        dashboardInitialized = true;
        initDashboardData();
    }
}

// User (non-admin) hanya bisa memantau: halaman Kelola Lampu & Kendali Cepat disembunyikan
function applyRoleRestrictions(role) {
    const isAdmin = role === "admin";
    const menuManage = document.getElementById("menu-item-manage");
    const quickControl = document.getElementById("quick-control-section");
    const clearAllBtn = document.getElementById("btn-clear-all-alerts");

    if (menuManage) menuManage.style.display = isAdmin ? "" : "none";
    if (quickControl) quickControl.style.display = isAdmin ? "" : "none";
    // User (monitoring-only) cuma boleh menandai alert dibaca, tidak boleh menghapus
    if (clearAllBtn) clearAllBtn.style.display = isAdmin ? "" : "none";

    // Kalau user non-admin nyasar ke halaman Kelola Lampu lewat URL/hash, tendang balik ke Beranda
    if (!isAdmin && location.hash.replace("#", "") === "manage") {
        navigateToHash("dashboard");
    }

    // Render ulang daftar alert kalau sudah pernah dirender, supaya tombol Hapus per-card ikut disembunyikan/dimunculkan
    if (typeof renderAlertList === "function" && document.getElementById("alert-list")) {
        renderAlertList();
    }
}

function initDashboardData() {
    initMap();

    fetch(`${API_BASE_URL}/api/devices-latest`)
        .then(response => response.json())
        .then(dbData => {
            console.log("Memuat data node dari PostgreSQL:", dbData);

            dbData.forEach(node => {
                const deviceId = node.id;

                devicesData[deviceId] = {
                    id: deviceId,
                    sector: node.sector,
                    health: node.health || "Healthy",
                    uptime: parseFloat(node.uptime) || 0,
                    volt: parseFloat(node.volt) || 0,
                    current: parseFloat(node.current) || 0,
                    power: parseFloat(node.power) || 0,
                    lat: parseFloat(node.lat),
                    lng: parseFloat(node.lng),
                    alerts: node.health === "Healthy" ? 0 : 1,
                    dim: node.dim !== undefined ? parseInt(node.dim) : 8
                };

                // === PERBAIKAN DI SINI: Inisialisasi telemetryHistory dinamis jika belum ada ===
                if (!telemetryHistory[deviceId]) {
                    telemetryHistory[deviceId] = {
                        labels: ["02:00", "04:00", "06:00", "08:00", "10:00", "12:00", "14:00"],
                        volt: [node.volt, node.volt, node.volt, node.volt, node.volt, node.volt, node.volt],
                        ampere: [node.current, node.current, node.current, node.current, node.current, node.current, node.current],
                        watt: [node.power, node.power, node.power, node.power, node.power, node.power, node.power]
                    };
                }

                addDeviceToDropdowns(deviceId, node.sector);
                addNewMapMarker(devicesData[deviceId]);
            });

            const defaultDevice = devicesData["L-107"] ? "L-107" : Object.keys(devicesData)[0];
            if (defaultDevice) {
                switchDevice(defaultDevice);
            }

            fetchSectorSettings();
            connectWebSocket();
        })
        .catch(err => {
            console.error("Gagal memuat data awal dari database:", err);
            switchDevice("L-102");
            fetchSectorSettings();
            connectWebSocket();
        })
        .finally(() => {
            // Buka halaman sesuai URL saat pertama kali dimuat (deep link / refresh)
            const initialPage = (location.hash || "#dashboard").replace("#", "");
            if (initialPage !== "dashboard") {
                navigateToHash(initialPage);
            }
        });
}

document.addEventListener("DOMContentLoaded", () => {
    // Kalau sesi login sebelumnya masih tersimpan, langsung masuk tanpa login ulang
    const savedRole = sessionStorage.getItem("acw_role");
    const savedToken = sessionStorage.getItem("acw_token");
    if (savedRole && savedToken) {
        enterDashboard(savedRole, savedToken);
    }
});

// 1. Data Koordinat Lampu dengan Atribut Sektor Baru (Sektor 1 & Sektor 2)
let devicesData = {
    // === SEKTOR 1: JALAN TUNJUNGAN ===
    "L-101": {
        id: "L-101",
        sector: "Sektor 1 (Jalan Tunjungan)",
        uptime: 4500,
        volt: 221.2,
        current: 0.45,
        power: 99.5,
        lat: -7.25782,
        lng: 112.73797,
        alerts: 0,
        dim: 80
    },
    "L-102": {
        id: "L-102",
        sector: "Sektor 1 (Jalan Tunjungan)",
        uptime: 8200,
        volt: 220.5,
        current: 0.45,
        power: 99.2,
        lat: -7.25828,
        lng: 112.73823,
        alerts: 1,
        dim: 80
    },
    "L-103": {
        id: "L-103",
        sector: "Sektor 1 (Jalan Tunjungan)",
        uptime: 2100,
        volt: 222.0,
        current: 0.46,
        power: 102.1,
        lat: -7.25870,
        lng: 112.73850,
        alerts: 0,
        dim: 80
    },

    // === SEKTOR 2: KERTAJAYA (DEPAN ITS) ===
    "L-104": {
        id: "L-104",
        sector: "Sektor 2 (Kertajaya - Depan ITS)",
        uptime: 10350,
        volt: 195.0,
        current: 0.00,
        power: 0.0,
        lat: -7.279236,
        lng: 112.78966,
        alerts: 2,
        dim: 80
    },
    "L-105": {
        id: "L-105",
        sector: "Sektor 2 (Kertajaya - Depan ITS)",
        uptime: 3100,
        volt: 218.4,
        current: 0.44,
        power: 96.1,
        lat: -7.27936,
        lng: 112.78868,
        alerts: 0,
        dim: 80
    },
    "L-106": {
        id: "L-106",
        sector: "Sektor 2 (Kertajaya - Depan ITS)",
        uptime: 8900,
        volt: 215.1,
        current: 0.40,
        power: 86.0,
        lat: -7.27945,
        lng: 112.78804,
        alerts: 1,
        dim: 80
    }
};

// State Management Konfigurasi Default Sektor
let sectorSettings = {
    "Sektor 1 (Jalan Tunjungan)": { schedules: [{ time: "17:30", dim: 6, cct: 30 }, { time: "23:00", dim: 4, cct: 80 }, { time: "03:30", dim: 8, cct: 100 }] },
    "Sektor 2 (Kertajaya - Depan ITS)": { schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] }
};

// Jadwal kecerahan sekarang murni per sektor (tidak ada lagi mode per-lampu individu) -
// default 3 fase per sektor, admin bisa tambah sampai maksimal 6.
const MIN_SCHEDULE_PHASES = 2;
const MAX_SCHEDULE_PHASES = 10;
const PHASE_LABELS = [
    "Mulai Beroperasi (Sore)",
    "Hemat Energi (Tengah Malam)",
    "Antisipasi Kabut (Dini Hari)",
    "Fase Tambahan",
    "Fase Tambahan",
    "Fase Tambahan"
];
const PHASE_COLOR_CLASSES = ["phase-primary", "phase-warning", "phase-danger", "phase-info", "phase-success", "phase-purple"];
let currentManageSector = null;

// Template satu kartu fase - tombol hapus cuma muncul kalau jumlah fase sektor ini masih
// di atas minimum (3), supaya default 3 fase gak bisa dihapus habis
function schedulePhaseCardHTML(index, sched, totalPhases) {
    const n = index + 1;
    const colorClass = PHASE_COLOR_CLASSES[index % PHASE_COLOR_CLASSES.length];
    const label = PHASE_LABELS[index] || "Fase Tambahan";
    const canRemove = totalPhases > MIN_SCHEDULE_PHASES;

    return `
        <div class="card phase-card ${colorClass}">
            <div class="phase-card-header">
                <h3>Fase ${n}: ${label}</h3>
                ${canRemove ? `<button type="button" class="btn-remove-phase" onclick="removeSchedulePhase(${index})" title="Hapus fase ini" aria-label="Hapus fase ${n}">&times;</button>` : ""}
            </div>
            <div class="control-group" style="margin-top: 10px;">
                <label>Jam Mulai:</label>
                <input type="time" id="sched-time-${n}" value="${sched.time}" class="input-control" style="width: 100%; margin-bottom: 15px;">

                <label>Kecerahan: <span id="sched-dim-label-${n}">${sched.dim}</span> V</label>
                <input type="range" min="1" max="10" value="${sched.dim}" class="slider" id="sched-dim-${n}" oninput="document.getElementById('sched-dim-label-${n}').innerText=this.value" style="margin-bottom: 15px;">

                <label>Kehangatan Warna: <span id="sched-cct-label-${n}">${sched.cct}</span>%</label>
                <input type="range" min="0" max="100" value="${sched.cct}" class="slider" id="sched-cct-${n}" oninput="document.getElementById('sched-cct-label-${n}').innerText=this.value">
            </div>
        </div>`;
}

// Render ulang seluruh kartu fase jadwal milik satu sektor (dipanggil tiap ganti sektor,
// atau setelah fase ditambah/dihapus)
function renderSchedulePhases(sectorName) {
    currentManageSector = sectorName || null;
    const container = document.getElementById("schedule-phase-list");
    const addBtn = document.getElementById("btn-add-phase");
    const saveBtn = document.getElementById("btn-save-schedule");
    const hint = document.getElementById("phase-count-hint");
    if (!container) return;

    const settings = sectorName ? sectorSettings[sectorName] : null;
    const schedules = (settings && Array.isArray(settings.schedules)) ? settings.schedules : [];

    if (!sectorName || schedules.length === 0) {
        container.innerHTML = `<div class="empty-state-block">Pilih sektor dulu untuk mengatur jadwalnya.</div>`;
        if (addBtn) addBtn.disabled = true;
        if (saveBtn) saveBtn.disabled = true;
        if (hint) hint.innerText = "";
        return;
    }

    container.innerHTML = schedules
        .map((sched, i) => schedulePhaseCardHTML(i, sched, schedules.length))
        .join("");

    if (addBtn) addBtn.disabled = schedules.length >= MAX_SCHEDULE_PHASES;
    if (saveBtn) saveBtn.disabled = false;
    if (hint) hint.innerText = `${schedules.length} / ${MAX_SCHEDULE_PHASES} fase`;
}

// Dipanggil dari dropdown "Sektor Target" di halaman Kelola Lampu
function loadSectorSettingsToUI(sectorName) {
    renderSchedulePhases(sectorName);
}

// Baca nilai fase LANGSUNG dari input yang lagi tampil di form - sumber kebenaran saat
// ini, karena slider/waktu cuma nulis ke DOM (lihat oninput di schedulePhaseCardHTML),
// belum pernah ditulis balik ke sectorSettings sampai submit/tambah/hapus fase terjadi
function readSchedulePhasesFromDOM(count) {
    const phases = [];
    for (let i = 1; i <= count; i++) {
        const timeEl = document.getElementById(`sched-time-${i}`);
        const dimEl = document.getElementById(`sched-dim-${i}`);
        const cctEl = document.getElementById(`sched-cct-${i}`);
        if (!timeEl || !dimEl || !cctEl) continue;
        phases.push({
            time: timeEl.value,
            dim: parseInt(dimEl.value, 10),
            cct: parseInt(cctEl.value, 10)
        });
    }
    return phases;
}

// Tombol "+ Tambah Fase" - nambah satu fase baru (nilai default, admin edit sendiri),
// dikunci di 6 fase maksimal lewat disabled state tombol
function addSchedulePhase() {
    if (!currentManageSector) return;
    const settings = sectorSettings[currentManageSector];
    if (!settings || !Array.isArray(settings.schedules)) return;
    if (settings.schedules.length >= MAX_SCHEDULE_PHASES) return;

    // Sinkronkan dulu editan yang sedang berjalan di form sebelum jumlah kartu berubah,
    // supaya perubahan waktu/kecerahan yang belum di-"Simpan Jadwal" tidak hilang
    settings.schedules = readSchedulePhasesFromDOM(settings.schedules.length);
    settings.schedules.push({ time: "12:00", dim: 5, cct: 50 });
    renderSchedulePhases(currentManageSector);
}

// Hapus satu fase - dikunci di 3 fase minimum (default) lewat guard di sini + tombol
// hapus yang cuma dirender kalau totalnya masih di atas minimum
function removeSchedulePhase(index) {
    if (!currentManageSector) return;
    const settings = sectorSettings[currentManageSector];
    if (!settings || !Array.isArray(settings.schedules)) return;
    if (settings.schedules.length <= MIN_SCHEDULE_PHASES) return;

    settings.schedules = readSchedulePhasesFromDOM(settings.schedules.length);
    settings.schedules.splice(index, 1);
    renderSchedulePhases(currentManageSector);
}

// Tombol "Simpan Jadwal" - PUT ke backend (admin-only lewat X-ACW-Token), yang lalu
// menyimpan ke Postgres DAN push konfigurasi ke tiap lampu fisik sektor ini via MQTT
// (lihat routes_schedules.py). Tanpa ini, jadwal cuma hidup di memori tab browser.
function saveSectorSchedule() {
    if (!currentManageSector) return;
    const settings = sectorSettings[currentManageSector];
    if (!settings || !Array.isArray(settings.schedules)) return;

    const phases = readSchedulePhasesFromDOM(settings.schedules.length);
    const saveBtn = document.getElementById("btn-save-schedule");
    if (saveBtn) saveBtn.disabled = true;

    fetch(`${API_BASE_URL}/api/sector-schedules`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
            'X-ACW-Token': authToken || ''
        },
        body: JSON.stringify({ sector: currentManageSector, schedules: phases })
    })
        .then(res => {
            if (res.ok) return res.json();
            return res.json()
                .catch(() => ({}))
                .then(data => { throw new Error(data?.error || `HTTP ${res.status}`); });
        })
        .then(() => {
            settings.schedules = phases; // sinkronkan state lokal dengan yang barusan tersimpan
            console.log(`Jadwal sektor '${currentManageSector}' berhasil disimpan & dipush ke device.`);
        })
        .catch(err => {
            console.error("Gagal menyimpan jadwal sektor:", err);
            addAlert({
                nodeId: currentManageSector,
                severity: 'warning',
                type: 'schedule_save_failed',
                message: `Gagal menyimpan jadwal sektor "${currentManageSector}": ${err.message}`
            });
        })
        .finally(() => {
            if (saveBtn) saveBtn.disabled = false;
        });
}


let map;
let markers = {};

function initMap() {
    map = new maplibregl.Map({
        container: 'map',
        style: 'https://tiles.openfreemap.org/styles/bright',
        center: [112.7377, -7.2578],
        zoom: 18.5,
        pitch: 65,
        bearing: -30
    });

    Object.keys(devicesData).forEach(key => {
        const data = devicesData[key];

        // Membuat kontainer luar untuk pinpoint
        const el = document.createElement('div');
        el.className = 'custom-pinpoint';
        el.style.cursor = 'pointer';
        el.style.width = '32px';
        el.style.height = '32px';
        el.style.transition = 'transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)';

        // Memasukkan SVG bentuk pinpoint/marker standar yang bisa diubah warnanya via atribut 'fill'
        el.innerHTML = `
            <svg viewBox="0 0 24 24" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <path class="pin-path" d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z" 
                fill="#94a3b8" stroke="#ffffff" stroke-width="1.5" style="transition: fill 0.3s ease;"/>
            </svg>
        `;

        // Offset anchor diatur ke 'bottom' agar ujung bawah lancip pinpoint tepat berada di koordinat
        const marker = new maplibregl.Marker({ element: el, anchor: 'bottom' })
            .setLngLat([data.lng, data.lat])
            .addTo(map);

        // PERBAIKAN DI SINI: Menggunakan "device-selector" sesuai ID di HTML
        marker.getElement().addEventListener('click', () => {
            onMarkerClick(data);
        });

        markers[key] = marker;
    });
}

function updateLifespanUI(uptimeHours) {
    const maxLifetime = 10000;
    const container = document.getElementById("lifespan-container");
    const bar = document.getElementById("lifespan-bar");
    const note = document.getElementById("lifespan-note");
    const uptimeText = document.getElementById("uptime-value");

    uptimeText.innerText = uptimeHours.toLocaleString('id-ID');

    let percentage = (uptimeHours / maxLifetime) * 100;
    if (percentage > 100) percentage = 100;
    bar.style.width = percentage + "%";

    container.classList.remove("warning-state", "danger-state");

    if (uptimeHours >= 10000) {
        container.classList.add("danger-state");
        bar.style.backgroundColor = "var(--danger)";
        note.innerText = "KRITIS: Perangkat melampaui batas usia kerja. (Perlu Perawatan)";
    } else if (uptimeHours >= 8000) {
        container.classList.add("warning-state");
        bar.style.backgroundColor = "var(--warning)";
        note.innerText = "PERINGATAN: Memasuki batas usia pakai optimal.";
    } else {
        bar.style.backgroundColor = "var(--primary)";
        note.innerText = "Kondisi Operasional Normal";
    }
}

// Fungsi memperbarui visual bentuk pinpoint berdasarkan status aktif dan tingkat lifespan
function updateMarkerStyles(activeId) {
    Object.keys(markers).forEach(key => {
        const markerElement = markers[key].getElement();
        const svgElement = markerElement.querySelector('svg'); // Targetkan elemen SVG di dalam marker
        const pinPath = markerElement.querySelector('.pin-path');
        const data = devicesData[key];

        if (key === activeId) {
            // Pinpoint aktif: Membesar signifikan (Aman untuk koordinat MapLibre)
            if (svgElement) {
                svgElement.style.transform = 'scale(1.5)'; // Ubah ke 1.6x atau sesuaikan tingkat kebesarannya
                svgElement.style.transformOrigin = 'bottom center'; // Titik tumpu perbesaran di ujung bawah pin
                svgElement.style.transition = 'transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)';
            }
            markerElement.style.zIndex = '10'; // Naik ke tumpukan paling atas

            if (pinPath) {
                if (data.uptime >= 10000) {
                    pinPath.setAttribute('fill', '#f23d3d'); // Merah (Critical)
                } else if (data.uptime >= 8000) {
                    pinPath.setAttribute('fill', '#ffb800'); // Kuning (Warning)
                } else {
                    pinPath.setAttribute('fill', '#10b981'); // Hijau (Healthy)
                }
            }
        } else {
            // Pinpoint tidak aktif: Ukuran kembali normal
            if (svgElement) {
                svgElement.style.transform = 'scale(1.0)';
            }
            markerElement.style.zIndex = '1';
            if (pinPath) pinPath.setAttribute('fill', '#94a3b8');
        }
    });
}

function switchDevice(deviceId) {
    const data = devicesData[deviceId];
    if (!data) return;

    // 1. Perbarui Informasi Atas (Card Data) - Hanya jika elemennya ada di halaman aktif
    const currentDeviceEl = document.getElementById("current-device-id");
    if (currentDeviceEl) currentDeviceEl.innerText = data.id;

    const powerEl = document.getElementById("power-value");
    if (powerEl) powerEl.innerText = data.power;

    const voltEl = document.getElementById("volt-value");
    if (voltEl) voltEl.innerText = data.volt;

    const currentValEl = document.getElementById("current-value");
    if (currentValEl) currentValEl.innerText = data.current;

    const latEl = document.getElementById("lat-value");
    if (latEl) latEl.innerText = data.lat.toFixed(4);

    const lngEl = document.getElementById("lng-value");
    if (lngEl) lngEl.innerText = data.lng.toFixed(4);

    // Sinkronisasi Tingkat Dimming di Kendali Cepat Dashboard
    if (data.dim !== undefined) {
        const dimLabel = document.getElementById("dim-label");
        if (dimLabel) dimLabel.innerText = data.dim;

        const dimSlider = document.getElementById("dim-slider");
        if (dimSlider) dimSlider.value = data.dim;
    }

    // Badge count dikelola oleh updateAlertBadge() dari sistem alert terpusat
    updateAlertBadge();

    // Sinkronisasi dropdown pemilih lampu di Dashboard
    const deviceSelector = document.getElementById("device-selector");
    if (deviceSelector) deviceSelector.value = deviceId;

    // Update status indicator
    // Update status indicator secara dinamis berdasarkan threshold uptime
    const statusText = document.getElementById("status-text");
    if (statusText) {
        statusText.className = "status-indicator";

        // Logika Threshold Batas Umur Waktu (Uptime)
        if (data.uptime >= 10000) {
            statusText.innerText = "Perlu Perawatan"; // Teks disesuaikan logika umur
            statusText.classList.add("status-critical");
        } else if (data.uptime >= 8000) {
            statusText.innerText = "Peringatan";          // Teks disesuaikan logika umur
            statusText.classList.add("status-warning");
        } else {
            statusText.innerText = "Baik";          // Teks disesuaikan logika umur
            statusText.classList.add("status-healthy");
        }

        // Perbarui data database lokal agar teks statusnya tetap tersimpan sinkron
        data.health = statusText.innerText;
    }

    // Panggil fungsi lifespan jika fungsi tersebut ada
    if (typeof updateLifespanUI === "function") {
        updateLifespanUI(data.uptime);
    }

    // Panggil fungsi update marker jika ada
    if (typeof updateMarkerStyles === "function") {
        updateMarkerStyles(deviceId);
    }

    // 2. ISI DATA KE PANEL DETIL PETA BERDASARKAN SEKTOR AKTIF SEBAGAI SATU-SATU NYA SUMBER KEBENARAN
    const activeSector = data.sector;
    const settings = sectorSettings[activeSector] || null;
    if (settings) {
        const panelNodeId = document.getElementById("panel-node-id");
        if (panelNodeId) panelNodeId.innerText = deviceId;

        const panelCurrentDim = document.getElementById("panel-current-dim");
        if (panelCurrentDim && data.dim !== undefined) {
            panelCurrentDim.innerText = data.dim;
        }

        // Update jadwal fase rtc di panel peta jika elemennya ada
        if (Array.isArray(settings.schedules)) {
            settings.schedules.forEach((sched, index) => {
                const i = index + 1;
                const timeEl = document.getElementById(`panel-time-${i}`);
                const dimEl = document.getElementById(`panel-dim-${i}`);
                const cctEl = document.getElementById(`panel-cct-${i}`);

                if (timeEl) timeEl.innerText = sched.time;
                if (dimEl) dimEl.innerText = sched.dim;
                if (cctEl) cctEl.innerText = sched.cct;
            });
        }
    }

    // 3. ANIMASI RE-LAYOUT MAP & FLY TO
    const container = document.querySelector(".map-split-container");
    if (container && !container.classList.contains("panel-open")) {
        container.classList.add("panel-open");
    }

    if (typeof map !== 'undefined' && map) {
        // Melakukan resize berkala selama transisi CSS berjalan agar peta tidak macet
        let resizeInterval = setInterval(() => { map.resize(); }, 16);
        setTimeout(() => { clearInterval(resizeInterval); }, 500); // Berhenti setelah 500ms

        map.flyTo({
            center: [data.lng, data.lat],
            zoom: 18.5,
            essential: true,
            speed: 0.6
        });
    }

    // Sinkronisasi jika tab manage sedang aktif - jadwal ikut pindah ke sektor milik
    // lampu yang baru aktif (jadwal sekarang murni per sektor, bukan per lampu)
    const pageManage = document.getElementById("page-manage");
    if (pageManage && pageManage.style.display === "block" && data.sector) {
        const sectorSelectorInput = document.getElementById("sector-selector-input");
        if (sectorSelectorInput) sectorSelectorInput.value = data.sector;
        renderSchedulePhases(data.sector);
    }
}

// Fungsi menutup kembali panel informasi kanan
function closeMapPanel() {
    const container = document.querySelector(".map-split-container");
    if (container) {
        container.classList.remove("panel-open");

        // Beri jeda penyesuaian ulang peta setelah panel tertutup penuh
        let resizeInterval = setInterval(() => { if (map) map.resize(); }, 16);
        setTimeout(() => { clearInterval(resizeInterval); }, 500);
    }
}

function updateDimLabel(val) { document.getElementById("dim-label").innerText = val; }
function updateCctLabel(val) { document.getElementById("cct-label").innerText = val; }

let dimControlDebounceTimer = null;

function sendDimControl(val) {
    const currentDeviceId = document.getElementById("current-device-id")?.innerText;
    if (!currentDeviceId || currentDeviceId === "-") return;

    const dimVal = parseInt(val);
    if (isNaN(dimVal) || dimVal < 0 || dimVal > 100) {
        console.error('Nilai kecerahan tidak valid:', val);
        return;
    }

    // Hapus timer sebelumnya untuk mencegah spam request saat slider digeser cepat
    if (dimControlDebounceTimer) {
        clearTimeout(dimControlDebounceTimer);
    }

    dimControlDebounceTimer = setTimeout(() => {
        // Endpoint ini sesuai dengan route "POST /api/lights/:id/command" di Node-RED
        // (endpoint lama "/api/control/dim" tidak pernah ada di flow, jadi command tidak pernah sampai ke ESP32)
        fetch(`${API_BASE_URL}/api/lights/${currentDeviceId}/command`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                // Backend menolak perintah ini kalau token bukan milik sesi admin (lihat light_command_fn di Node-RED)
                'X-ACW-Token': authToken || ''
            },
            body: JSON.stringify({ id: currentDeviceId, dim: dimVal })
        })
            .then(res => {
                if (res.status === 403) throw new Error('forbidden');
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(data => {
                console.log(`[HTTP] Perintah kecerahan (${dimVal}%) berhasil dikirim ke ${currentDeviceId}:`, data);
            })
            .catch(err => {
                const isForbidden = err.message === 'forbidden';
                console.error("[HTTP] Gagal mengirim perintah kecerahan ke perangkat:", err);
                addAlert({
                    nodeId: currentDeviceId,
                    severity: 'warning',
                    type: 'command_failed',
                    message: isForbidden
                        ? `Perintah kecerahan ke Lampu ${currentDeviceId} ditolak server: hanya admin yang bisa mengubah kecerahan.`
                        : `Perintah kecerahan ke Lampu ${currentDeviceId} gagal terkirim. Periksa koneksi ke server.`,
                    volt: 0,
                    current: 0,
                    power: 0,
                    threshold: {},
                    timestamp: new Date(),
                    isRead: false,
                    isDismissed: false
                });
            });
    }, 150);
}

// Catatan: Inisialisasi awal dipindahkan ke DOMContentLoaded listener

// FUNGSI NAVIGASI TAB HALAMAN (Sudah disatukan & dibersihkan dari duplikasi)
function navigateTo(pageId, element) {
    // Halaman Kelola Lampu khusus admin — tolak akses role lain walau dibuka lewat hash URL langsung
    if (pageId === 'manage' && currentRole !== 'admin') {
        pageId = 'dashboard';
        element = document.querySelector('#sidebar-menu li[data-page="dashboard"]');
    }

    // Sembunyikan semua halaman
    document.getElementById("page-dashboard").style.display = "none";
    document.getElementById("page-manage").style.display = "none";
    document.getElementById("page-telemetry").style.display = "none";
    document.getElementById("page-alerts").style.display = "none";

    // Hapus kelas aktif dari semua li di menu sidebar
    const menuItems = document.querySelectorAll("#sidebar-menu li");
    menuItems.forEach(item => item.classList.remove("active"));

    // Tampilkan halaman target & beri kelas aktif pada tombol navigasi
    if (pageId === 'dashboard') {
        document.getElementById("page-dashboard").style.display = "block";
        if (map) map.resize();
    } else if (pageId === 'manage') {
        document.getElementById("page-manage").style.display = "block";

        // Default buka sektor milik lampu yang sedang aktif, kalau belum ada pilih
        // sektor pertama yang tersedia di dropdown (jadwal sekarang murni per sektor)
        const currentId = document.getElementById("current-device-id").innerText;
        const sectorSelectorInput = document.getElementById("sector-selector-input");
        const defaultManageSector = (currentId && devicesData[currentId]?.sector)
            || sectorSelectorInput?.options[1]?.value
            || "";

        if (sectorSelectorInput) sectorSelectorInput.value = defaultManageSector;
        renderSchedulePhases(defaultManageSector);
    } else if (pageId === 'telemetry') {
        document.getElementById("page-telemetry").style.display = "block";

        // Default buka sektor milik lampu yang sedang aktif (dari peta/dashboard), kalau
        // belum ada pilih sektor pertama yang tersedia di dropdown
        const activeId = document.getElementById("current-device-id").innerText;
        const telSectorSelector = document.getElementById("telemetry-sector-selector");
        const defaultSector = (activeId && devicesData[activeId]?.sector)
            || telSectorSelector?.options[1]?.value
            || "";

        if (telSectorSelector) telSectorSelector.value = defaultSector;

        // Beri setTimeout agar browser menyelesaikan render display: block terlebih dahulu
        // (canvas Chart.js butuh dimensi elemen yang sudah "block", bukan "none")
        setTimeout(() => {
            renderTelemetrySectorList(defaultSector);
        }, 50);
    } else if (pageId === 'alerts') {
        document.getElementById("page-alerts").style.display = "block";
        fetchAlertsFromDB();
    }

    element.classList.add("active");

    // Simpan halaman aktif ke URL supaya tombol back browser & refresh/berbagi tautan tetap berfungsi
    if (location.hash !== "#" + pageId) {
        history.pushState({ page: pageId }, "", "#" + pageId);
    }
}

// Buka halaman sesuai hash URL (dipakai saat load awal & tombol back/forward browser)
function navigateToHash(pageId) {
    const li = document.querySelector(`#sidebar-menu li[data-page="${pageId}"]`);
    if (li) navigateTo(pageId, li);
}

window.addEventListener("popstate", () => {
    const pageId = (location.hash || "#dashboard").replace("#", "");
    navigateToHash(pageId);
});

// DATA HISTORIS PZEM (Mock Data 12 Jam Terakhir)
const telemetryHistory = {
    "L-101": {
        labels: ["02:00", "04:00", "06:00", "08:00", "10:00", "12:00", "14:00"],
        volt: [218.4, 219.1, 220.5, 221.8, 220.1, 219.5, 220.2],
        ampere: [0.82, 0.79, 0.41, 0.12, 0.05, 0.05, 0.38],
        watt: [179.1, 173.0, 90.4, 26.6, 11.0, 11.0, 83.6]
    },
    "L-102": {
        labels: ["02:00", "04:00", "06:00", "08:00", "10:00", "12:00", "14:00"],
        volt: [221.2, 220.8, 222.1, 223.0, 221.5, 220.9, 221.4],
        ampere: [0.91, 0.88, 0.45, 0.15, 0.08, 0.08, 0.42],
        watt: [201.2, 194.3, 99.9, 33.4, 17.7, 17.7, 92.9]
    },
    "L-103": {
        labels: ["02:00", "04:00", "06:00", "08:00", "10:00", "12:00", "14:00"],
        volt: [220.1, 221.4, 219.8, 220.5, 221.2, 220.7, 221.1],
        ampere: [0.45, 0.45, 0.35, 0.10, 0.02, 0.02, 0.25],
        watt: [99.5, 99.5, 76.9, 22.0, 4.4, 4.4, 55.2]
    },
    "L-104": {
        labels: ["02:00", "04:00", "06:00", "08:00", "10:00", "12:00", "14:00"],
        volt: [195.0, 194.8, 195.2, 195.0, 194.5, 195.1, 195.0],
        ampere: [0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
        watt: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    },
    "L-105": {
        labels: ["02:00", "04:00", "06:00", "08:00", "10:00", "12:00", "14:00"],
        volt: [217.5, 218.0, 218.4, 219.1, 218.8, 218.2, 218.5],
        ampere: [0.78, 0.75, 0.40, 0.10, 0.04, 0.04, 0.35],
        watt: [169.6, 163.5, 87.4, 21.9, 8.8, 8.8, 76.5]
    },
    "L-106": {
        labels: ["02:00", "04:00", "06:00", "08:00", "10:00", "12:00", "14:00"],
        volt: [214.8, 215.1, 215.5, 216.0, 215.3, 214.9, 215.2],
        ampere: [0.70, 0.68, 0.38, 0.09, 0.03, 0.03, 0.32],
        watt: [150.4, 146.3, 81.9, 19.4, 6.5, 6.5, 68.9]
    }
};

// Satu instance Chart.js per lampu (bukan satu global lagi) karena sekarang semua lampu
// dalam sektor terpilih ditampilkan sekaligus, bukan gantian lewat dropdown.
let telemetryChartInstances = {};
let currentTelemetrySector = null;

// INISIALISASI / UPDATE CARD RATA-RATA TELEMETRY (per lampu, id elemen bersufiks deviceId)
function updateTelemetrySummary(deviceId) {
    const data = telemetryHistory[deviceId];
    const voltEl = document.getElementById(`avg-volt-${deviceId}`);
    const currentEl = document.getElementById(`avg-current-${deviceId}`);
    const powerEl = document.getElementById(`avg-power-${deviceId}`);

    // Blok kartu lampu ini belum/tidak sedang dirender (mis. sektor sudah dipindah) - abaikan
    if (!voltEl || !currentEl || !powerEl) return;

    // Jika data belum ada/belum selesai di-fetch, set tampilan default ke 0
    if (!data) {
        voltEl.innerText = "0 V";
        currentEl.innerText = "0 A";
        powerEl.innerText = "0 W";
        return;
    }

    // Ambil array dengan toleransi nama key (volt, current/ampere, power/watt)
    const voltArr = data.volt || [];
    const currentArr = data.current || data.ampere || [];
    const powerArr = data.power || data.watt || [];

    // Helper kalkulasi rata-rata yang tahan NaN
    const calcAvg = (arr) => {
        if (!arr || !Array.isArray(arr) || arr.length === 0) return "0.0";
        const sum = arr.reduce((acc, val) => acc + (parseFloat(val) || 0), 0);
        return (sum / arr.length).toFixed(1);
    };

    voltEl.innerText = `${calcAvg(voltArr)} V`;
    currentEl.innerText = `${calcAvg(currentArr)} A`;
    powerEl.innerText = `${calcAvg(powerArr)} W`;
}

// FUNGSI MENGGAMBAR/DRAW CHART.JS (canvas & instance per lampu: telemetryChart-{deviceId})
function drawChart(deviceId) {
    const dataSet = telemetryHistory[deviceId];
    if (!dataSet) return;

    const canvas = document.getElementById(`telemetryChart-${deviceId}`);
    if (!canvas) return; // Blok lampu ini sudah tidak ada di DOM (sektor sudah dipindah)

    // Ambil array dengan toleransi nama key
    const labels = dataSet.labels || [];
    const voltArr = dataSet.volt || [];
    const currentArr = dataSet.current || dataSet.ampere || [];
    const powerArr = dataSet.power || dataSet.watt || [];

    const ctx = canvas.getContext('2d');

    if (telemetryChartInstances[deviceId]) {
        telemetryChartInstances[deviceId].destroy();
    }

    telemetryChartInstances[deviceId] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Tegangan (Volt)',
                    data: voltArr,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    yAxisID: 'y-volt',
                    tension: 0.3,
                    fill: true
                },
                {
                    label: 'Arus (Ampere)',
                    data: currentArr,
                    borderColor: '#10b981',
                    backgroundColor: 'transparent',
                    yAxisID: 'y-ampere',
                    tension: 0.3
                },
                {
                    label: 'Daya Aktif (Watt)',
                    data: powerArr,
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.05)',
                    yAxisID: 'y-watt',
                    tension: 0.3,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#94a3b8' }
                }
            },
            scales: {
                x: {
                    grid: { color: '#1e293b' },
                    ticks: { color: '#94a3b8' }
                },
                'y-volt': {
                    type: 'linear',
                    position: 'left',
                    grid: { color: '#1e293b' },
                    ticks: { color: '#3b82f6' },
                    title: { display: true, text: 'Volt (V)', color: '#3b82f6' },
                    min: 200,
                    max: 250
                },
                'y-ampere': {
                    type: 'linear',
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#10b981' },
                    title: { display: true, text: 'Arus (A)', color: '#10b981' },
                    min: 0,
                    max: 2
                },
                'y-watt': {
                    type: 'linear',
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#f59e0b' },
                    title: { display: true, text: 'Daya (W)', color: '#f59e0b' },
                    min: 0,
                    max: 280
                }
            }
        }
    });
}

function renderTelemetryChart(deviceId) {
    if (!deviceId) return;

    // Fetch data historis dari backend
    fetch(`${API_BASE_URL}/api/telemetry-history?device_id=${deviceId}`)
        .then(response => response.json())
        .then(data => {
            // Jika backend mengembalikan format array rows (karena query SELECT di PostgreSQL),
            // konversikan ke objek berisi array yang sesuai dengan kebutuhan Chart.js
            if (Array.isArray(data)) {
                const transformed = {
                    labels: [],
                    volt: [],
                    ampere: [],
                    watt: [],
                    current: [],
                    power: []
                };
                data.forEach(row => {
                    transformed.labels.push(row.time_label || "");
                    transformed.volt.push(row.volt !== undefined ? parseFloat(row.volt) : 0);

                    const ampVal = row.ampere !== undefined ? parseFloat(row.ampere) : (row.current !== undefined ? parseFloat(row.current) : 0);
                    transformed.ampere.push(ampVal);
                    transformed.current.push(ampVal);

                    const wattVal = row.watt !== undefined ? parseFloat(row.watt) : (row.power !== undefined ? parseFloat(row.power) : 0);
                    transformed.watt.push(wattVal);
                    transformed.power.push(wattVal);
                });
                telemetryHistory[deviceId] = transformed;
            } else {
                telemetryHistory[deviceId] = data;

                // Normalisasi key untuk kompatibilitas data
                if (data) {
                    if (!data.ampere && data.current) data.ampere = data.current;
                    if (!data.watt && data.power) data.watt = data.power;
                }
            }

            // Render Chart & Update Card Rata-Rata setelah data dipastikan ADA
            drawChart(deviceId);
            updateTelemetrySummary(deviceId);
        })
        .catch(err => {
            console.error("Gagal memuat history telemetry saat refresh:", err);
            updateTelemetrySummary(deviceId); // fallback ke 0 jika error
        });
}

// Pill status kesehatan kecil di header tiap blok lampu (warna senada dengan pin peta)
function telemetryStatusPillHTML(health) {
    const map = {
        Healthy: ["telemetry-status-healthy", "Sehat"],
        Warning: ["telemetry-status-warning", "Perlu Perhatian"],
        Critical: ["telemetry-status-critical", "Kritis"]
    };
    const [cls, label] = map[health] || ["telemetry-status-warning", health || "Tidak Diketahui"];
    return `<span class="telemetry-status-pill ${cls}">${label}</span>`;
}

// Template HTML satu blok lampu: header + 3 kartu ringkasan + grafik, id-nya disufiks
// deviceId supaya banyak lampu bisa tampil sekaligus dalam satu sektor tanpa bentrok id
function telemetryLampBlockHTML(deviceId, health) {
    return `
        <div class="telemetry-lamp-block">
            <div class="telemetry-lamp-header">
                <span class="card-icon-badge badge-blue">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/></svg>
                </span>
                <h2>Tiang ${deviceId}</h2>
                ${telemetryStatusPillHTML(health)}
            </div>

            <div class="telemetry-summary-grid">
                <div class="card">
                    <div class="card-header-row">
                        <span class="card-icon-badge badge-blue"><svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></span>
                        <h3>Rata-rata Tegangan</h3>
                    </div>
                    <div class="big-value" style="color: #3b82f6;" id="avg-volt-${deviceId}">0.0 V</div>
                </div>
                <div class="card">
                    <div class="card-header-row">
                        <span class="card-icon-badge badge-green"><svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></span>
                        <h3>Rata-rata Arus</h3>
                    </div>
                    <div class="big-value" style="color: var(--success);" id="avg-current-${deviceId}">0.0 A</div>
                </div>
                <div class="card">
                    <div class="card-header-row">
                        <span class="card-icon-badge badge-amber"><svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/></svg></span>
                        <h3>Konsumsi Daya Kumulatif</h3>
                    </div>
                    <div class="big-value" style="color: var(--warning);" id="avg-power-${deviceId}">0.0 W</div>
                </div>
            </div>

            <div class="card" style="padding: 25px; position: relative; height: 380px;">
                <canvas id="telemetryChart-${deviceId}"></canvas>
            </div>
        </div>`;
}

// Render semua lampu milik satu sektor sekaligus (ganti dropdown per-lampu lama) - user
// tinggal scroll ke bawah untuk lihat histori tiap lampu, tidak perlu ganti-ganti pilihan
function renderTelemetrySectorList(sectorName) {
    currentTelemetrySector = sectorName || null;
    const container = document.getElementById("telemetry-sector-list");
    if (!container) return;

    // Bersihkan instance Chart.js lama supaya tidak nyangkut ke canvas yang sudah dibuang
    Object.values(telemetryChartInstances).forEach(chart => chart.destroy());
    telemetryChartInstances = {};

    if (!sectorName) {
        container.innerHTML = `<div class="empty-state-block">Pilih sektor dulu untuk melihat riwayat datanya.</div>`;
        return;
    }

    const deviceIds = Object.values(devicesData)
        .filter(d => d.sector === sectorName)
        .map(d => d.id)
        .sort();

    if (deviceIds.length === 0) {
        container.innerHTML = `<div class="empty-state-block">Belum ada lampu terdaftar di sektor ini.</div>`;
        return;
    }

    container.innerHTML = deviceIds
        .map(id => telemetryLampBlockHTML(id, devicesData[id].health))
        .join("");

    // Fetch histori & gambar grafik masing-masing lampu setelah blok-nya ada di DOM
    deviceIds.forEach(id => renderTelemetryChart(id));
}

// Dipanggil dari dropdown "Pilih Sektor" di halaman Riwayat Data
function changeTelemetrySector(sectorName) {
    renderTelemetrySectorList(sectorName);
}

// Fungsi untuk mengaktifkan/menonaktifkan input manual override
function toggleManualOverride(isUnlocked) {
    const dimSlider = document.getElementById("dim-slider");
    const cctSlider = document.getElementById("cct-slider");
    const lockStatusText = document.getElementById("lock-status-text");

    if (isUnlocked) {
        // Jika kunci dibuka, aktifkan slider
        dimSlider.removeAttribute("disabled");
        cctSlider.removeAttribute("disabled");

        lockStatusText.innerText = "AKTIF (SIAP DIKONTROL)";
        lockStatusText.style.color = "var(--success)";
    } else {
        // Jika dikunci kembali, matikan slider
        dimSlider.setAttribute("disabled", "true");
        cctSlider.setAttribute("disabled", "true");

        lockStatusText.innerText = "TERKUNCI";
        lockStatusText.style.color = "var(--text-muted)";
    }
}

// Ambil jadwal RTC sungguhan dari database (GET /api/sector-schedules, publik - dipakai
// juga oleh panel detail lampu di halaman Beranda yang bisa dilihat semua role), timpa
// default hardcode di atas. Sektor yang belum punya baris di DB tetap pakai default 3
// fase bawaan sampai admin menyimpan jadwalnya yang pertama kali.
function fetchSectorSettings() {
    fetch(`${API_BASE_URL}/api/sector-schedules`)
        .then(res => res.json())
        .then(grouped => {
            Object.keys(grouped).forEach(sector => {
                if (grouped[sector].length > 0) {
                    sectorSettings[sector] = { schedules: grouped[sector] };
                }
            });

            // Kalau tab Kelola Lampu kebetulan lagi kebuka pas fetch ini selesai, refresh
            // tampilan fase-nya dengan data server yang baru datang
            if (currentManageSector && grouped[currentManageSector]) {
                renderSchedulePhases(currentManageSector);
            }
        })
        .catch(err => console.error("Gagal memuat jadwal sektor dari server:", err))
        .finally(() => {
            if (document.getElementById("current-device-id")) {
                switchDevice(document.getElementById("current-device-id").innerText);
            }
        });
}


// ============================================================
//  ALERT INBOX — Data Store & State
// ============================================================

// Array utama penyimpanan semua objek alert
let alertsData = [];

// State filter aktif
let alertFilters = { severity: 'all', node: 'all', search: '' };

// Cooldown tracker: { "nodeId_type": timestamp_ms }
let alertCooldowns = {};

// Konstanta cooldown 60 detik
const ALERT_COOLDOWN_MS = 60000;

// ============================================================
//  ALERT INBOX — Fungsi Utama
// ============================================================

/**
 * Tambahkan alert baru ke alertsData.
 * Setelah ditambahkan, perbarui badge & re-render list (hanya jika halaman alerts aktif).
 */
function addAlert(alertObj) {
    // Cek cooldown: jika alert untuk nodeId+type yang sama sudah ada < 60 detik lalu, lewati
    const cooldownKey = `${alertObj.nodeId}_${alertObj.type}`;
    const lastTime = alertCooldowns[cooldownKey];
    const now = Date.now();
    if (lastTime && (now - lastTime) < ALERT_COOLDOWN_MS) {
        return; // Masih dalam periode cooldown, abaikan
    }
    alertCooldowns[cooldownKey] = now;

    // Pastikan objek memiliki ID unik
    if (!alertObj.id) {
        alertObj.id = 'alert_ws_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5);
    }
    if (!alertObj.timestamp) {
        alertObj.timestamp = new Date();
    }
    if (alertObj.isRead === undefined) alertObj.isRead = false;
    if (alertObj.isDismissed === undefined) alertObj.isDismissed = false;

    // Tambahkan ke awal array agar alert terbaru muncul di atas
    alertsData.unshift(alertObj);

    // Tambahkan node ke dropdown filter jika belum ada
    _addNodeToAlertFilter(alertObj.nodeId);

    // Perbarui badge unread
    updateAlertBadge();

    // Re-render hanya jika halaman alerts sedang ditampilkan
    const alertPage = document.getElementById('page-alerts');
    if (alertPage && alertPage.style.display !== 'none') {
        renderAlertList();
    }
}

/**
 * Render daftar alert ke #alert-list berdasarkan filter aktif.
 */
function renderAlertList() {
    const listEl = document.getElementById('alert-list');
    const emptyEl = document.getElementById('alert-empty-state');
    if (!listEl) return;

    // Ambil alert yang belum di-dismiss
    let filtered = alertsData.filter(a => !a.isDismissed);

    // Filter severity
    if (alertFilters.severity !== 'all') {
        filtered = filtered.filter(a => a.severity === alertFilters.severity);
    }

    // Filter node
    if (alertFilters.node !== 'all') {
        filtered = filtered.filter(a => a.nodeId === alertFilters.node);
    }

    // Filter pencarian teks
    if (alertFilters.search.trim() !== '') {
        const q = alertFilters.search.trim().toLowerCase();
        filtered = filtered.filter(a =>
            a.message.toLowerCase().includes(q) ||
            a.nodeId.toLowerCase().includes(q) ||
            a.type.toLowerCase().includes(q)
        );
    }

    // Update stats
    _updateAlertStats();

    // Tampilkan empty state jika kosong
    if (filtered.length === 0) {
        listEl.innerHTML = '';
        if (emptyEl) emptyEl.style.display = 'flex';
        return;
    }

    if (emptyEl) emptyEl.style.display = 'none';

    // Render setiap alert card
    listEl.innerHTML = filtered.map(alert => _buildAlertCardHTML(alert)).join('');
}

/**
 * Tandai satu alert sebagai sudah dibaca — update ke DB lalu re-fetch.
 */
function markAlertRead(alertId) {
    // Normalkan tipe: ID dari DB adalah integer, tapi onclick HTML selalu kirim string
    const normalizedId = typeof alertId === 'string' && !alertId.startsWith('alert_ws_')
        ? parseInt(alertId, 10)
        : alertId;

    // Optimistic UI update
    const alert = alertsData.find(a => a.id === normalizedId || String(a.id) === String(alertId));
    if (alert) {
        alert.isRead = true;
        updateAlertBadge();
        renderAlertList();
    }

    // Persist ke DB — hanya untuk alert dengan ID integer (dari DB)
    if (!String(alertId).startsWith('alert_ws_')) {
        fetch(`${API_BASE_URL}/api/alerts/${normalizedId}/read`, { method: 'PATCH' })
            .catch(err => console.error('Gagal mark-read alert ke DB:', err));
    }
}

/**
 * Tandai semua alert sebagai sudah dibaca — update ke DB.
 */
function markAllRead() {
    alertsData.forEach(a => { a.isRead = true; });
    updateAlertBadge();
    renderAlertList();

    fetch(`${API_BASE_URL}/api/alerts/mark-all-read`, { method: 'POST' })
        .catch(err => console.error('Gagal mark-all-read ke DB:', err));
}

/**
 * Hapus satu alert dari tampilan dan DB.
 */
function dismissAlert(alertId) {
    // Normalkan tipe: ID dari DB adalah integer, tapi onclick HTML selalu kirim string
    const normalizedId = typeof alertId === 'string' && !alertId.startsWith('alert_ws_')
        ? parseInt(alertId, 10)
        : alertId;

    // Optimistic UI update
    const alert = alertsData.find(a => a.id === normalizedId || String(a.id) === String(alertId));
    if (alert) {
        alert.isDismissed = true;
        updateAlertBadge();
        renderAlertList();
    }

    // Hapus dari DB — hanya untuk alert dengan ID integer (dari DB), bukan alert_ws_*
    if (!String(alertId).startsWith('alert_ws_')) {
        fetch(`${API_BASE_URL}/api/alerts/${normalizedId}`, {
            method: 'DELETE',
            headers: { 'X-ACW-Token': authToken || '' }
        })
            .catch(err => console.error('Gagal hapus alert dari DB:', err));
    }
}

/**
 * Hapus semua alert dari tampilan dan DB.
 */
function clearAllAlerts() {
    alertsData = [];
    alertCooldowns = {};
    updateAlertBadge();
    renderAlertList();

    fetch(`${API_BASE_URL}/api/alerts`, {
        method: 'DELETE',
        headers: { 'X-ACW-Token': authToken || '' }
    })
        .catch(err => console.error('Gagal hapus semua alert dari DB:', err));
}

/**
 * Perbarui badge angka unread di sidebar.
 */
function updateAlertBadge() {
    const unreadCount = alertsData.filter(a => !a.isRead && !a.isDismissed).length;
    const badgeEl = document.getElementById('alert-badge');
    if (badgeEl) {
        badgeEl.textContent = unreadCount > 0 ? unreadCount : '0';
        badgeEl.style.display = unreadCount > 0 ? 'inline-block' : 'inline-block';
    }
}

/**
 * Set filter (severity atau node) dan re-render.
 * @param {string} type    - 'severity' atau 'node'
 * @param {string} value   - nilai filter
 * @param {Element|null} pillEl - elemen tombol pill (untuk update kelas aktif)
 */
function setAlertFilter(type, value, pillEl) {
    alertFilters[type] = value;

    // Jika filter severity, update kelas aktif pada pill buttons
    if (type === 'severity' && pillEl) {
        const pills = document.querySelectorAll('#severity-filter-pills .filter-pill');
        pills.forEach(p => p.classList.remove('active'));
        pillEl.classList.add('active');
    }

    renderAlertList();
}

/**
 * Update filter pencarian teks dan re-render.
 */
function handleAlertSearch(value) {
    alertFilters.search = value;
    renderAlertList();
}

/**
 * Hasilkan pesan deskriptif Bahasa Indonesia berdasarkan tipe alert.
 */
function generateAlertMessage(type, nodeId, volt, current) {
    switch (type) {
        case 'voltage_spike':
            return `Lampu ${nodeId} terdeteksi lonjakan tegangan sebesar ${volt}V, melebihi batas aman 240V. Segera periksa kondisi jaringan listrik.`;
        case 'voltage_drop':
            return `Lampu ${nodeId} mengalami penurunan tegangan ke ${volt}V (di bawah 200V). Kemungkinan gangguan pasokan daya.`;
        case 'current_spike':
            return `Lampu ${nodeId} mendeteksi lonjakan arus listrik sebesar ${current}A, melampaui batas kritis 1.5A. Periksa kemungkinan korsleting.`;
        case 'current_high':
            return `Lampu ${nodeId} mencatat arus tinggi sebesar ${current}A (di atas 1.0A). Pantau secara berkala untuk mencegah kerusakan komponen.`;
        case 'offline':
            return `Lampu ${nodeId} terdeteksi tidak menyala atau tidak bertenaga. Tegangan terbaca ${volt}V, jauh di bawah batas operasional minimum.`;
        case 'power_high':
            const pow = (volt * current).toFixed(1);
            return `Lampu ${nodeId} mengonsumsi daya melebihi batas normal (${pow}W > 350W). Periksa beban listrik yang terhubung.`;
        default:
            return `Lampu ${nodeId} mengirimkan sinyal tidak normal. Mohon lakukan pengecekan langsung di lapangan.`;
    }
}

// ============================================================
//  ALERT INBOX — Helper Internal
// ============================================================

/**
 * Bangun HTML string untuk satu alert card.
 */
/** Bungkus path SVG jadi ikon outline kecil (gaya konsisten, bukan emoji) */
function _svgIcon(innerPaths, size = 16) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;">${innerPaths}</svg>`;
}

const _METRIC_ICON_VOLT = _svgIcon('<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>', 14);
const _METRIC_ICON_CURRENT = _svgIcon('<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>', 14);
const _METRIC_ICON_POWER = _svgIcon('<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>', 14);
const _METRIC_ICON_THRESHOLD = _svgIcon('<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>', 14);

function _buildAlertCardHTML(alert) {
    const isUnread = !alert.isRead;
    const severityLabel = { critical: 'KRITIS', warning: 'PERINGATAN', info: 'INFO' }[alert.severity] || 'INFO';
    const severityBadgeClass = { critical: 'badge-critical', warning: 'badge-warning', info: 'badge-info' }[alert.severity] || 'badge-info';
    const typeIcon = _getAlertTypeIcon(alert.type);
    const timestamp = alert.timestamp instanceof Date
        ? alert.timestamp.toLocaleString('id-ID', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
        : String(alert.timestamp);

    // Tentukan apakah nilai metrik anomali
    const voltAnomalous = alert.volt > 240 || alert.volt < 100;
    const voltWarn = alert.volt < 200 && alert.volt >= 100;
    const currentAnomalous = alert.current > 1.5;
    const currentWarn = alert.current > 1.0 && alert.current <= 1.5;
    const powerWarn = alert.power > 350;

    const voltClass = voltAnomalous ? 'anomalous' : (voltWarn ? 'warn-value' : '');
    const currentClass = currentAnomalous ? 'anomalous' : (currentWarn ? 'warn-value' : '');
    const powerClass = powerWarn ? 'warn-value' : '';

    const unreadDot = isUnread ? '<span class="unread-dot"></span>' : '';
    const cardClass = `alert-card severity-${alert.severity}${isUnread ? ' unread' : ''}`;

    // Tombol "Tandai Dibaca" hanya tampil jika belum dibaca
    const readBtn = !alert.isRead
        ? `<button class="btn-read" onclick="markAlertRead('${alert.id}')">${_svgIcon('<path d="M20 6 9 17l-5-5"/>')} Tandai Dibaca</button>`
        : '';

    // Tombol "Hapus" cuma buat admin - user (monitoring-only) cuma boleh menandai dibaca
    const dismissBtn = currentRole === 'admin'
        ? `<button class="btn-dismiss" onclick="dismissAlert('${alert.id}')">${_svgIcon('<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>')} Hapus</button>`
        : '';

    return `
    <div class="${cardClass}" id="card-${alert.id}">
        <div class="alert-card-header">
            <div class="alert-card-header-left">
                ${unreadDot}
                <span class="alert-severity-badge ${severityBadgeClass}">${severityLabel}</span>
                <span class="alert-node-id">${alert.nodeId}</span>
                <span style="display:inline-flex; color: var(--text-muted);">${typeIcon}</span>
            </div>
            <span class="alert-timestamp">${timestamp}</span>
        </div>
        <p class="alert-message">${alert.message}</p>
        <div class="alert-metrics">
            <div class="alert-metric-item">
                <span class="alert-metric-label">${_METRIC_ICON_VOLT} Tegangan:</span>
                <span class="alert-metric-value ${voltClass}">${alert.volt !== undefined ? alert.volt.toFixed(1) : '–'} V</span>
            </div>
            <div class="alert-metric-item">
                <span class="alert-metric-label">${_METRIC_ICON_CURRENT} Arus:</span>
                <span class="alert-metric-value ${currentClass}">${alert.current !== undefined ? alert.current.toFixed(3) : '–'} A</span>
            </div>
            <div class="alert-metric-item">
                <span class="alert-metric-label">${_METRIC_ICON_POWER} Daya:</span>
                <span class="alert-metric-value ${powerClass}">${alert.power !== undefined ? alert.power.toFixed(1) : '–'} W</span>
            </div>
            ${alert.threshold && Object.keys(alert.threshold).length > 0 ? `
            <div class="alert-metric-item">
                <span class="alert-metric-label">${_METRIC_ICON_THRESHOLD} Ambang Batas:</span>
                <span class="alert-metric-value">${_formatThreshold(alert.threshold)}</span>
            </div>` : ''}
        </div>
        <div class="alert-footer">
            <span class="alert-type-label">${_formatAlertType(alert.type)}</span>
            <div class="alert-actions">
                ${readBtn}
                ${dismissBtn}
            </div>
        </div>
    </div>`;
}

/** Kembalikan ikon SVG outline berdasarkan tipe alert (bukan emoji, konsisten dengan gaya desain lain) */
function _getAlertTypeIcon(type) {
    const icons = {
        voltage_spike: '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
        voltage_drop: '<polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/>',
        current_spike: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
        current_high: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
        offline: '<circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>',
        power_high: '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>',
        command_failed: '<line x1="1" y1="1" x2="23" y2="23"/><path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"/><path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"/><path d="M10.71 5.05A16 16 0 0 1 22.58 9"/><path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/>'
    };
    return _svgIcon(icons[type] || '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>', 16);
}

/** Format label tipe alert yang lebih mudah dibaca */
function _formatAlertType(type) {
    const labels = {
        voltage_spike: 'Lonjakan Tegangan',
        voltage_drop: 'Penurunan Tegangan',
        current_spike: 'Lonjakan Arus',
        current_high: 'Arus Tinggi',
        offline: 'Perangkat Padam',
        power_high: 'Konsumsi Daya Tinggi',
        command_failed: 'Perintah Gagal Terkirim'
    };
    return labels[type] || type;
}

/** Format nilai threshold ke string */
function _formatThreshold(threshold) {
    const parts = [];
    if (threshold.volt !== undefined) parts.push(`Tegangan: ${threshold.volt}V`);
    if (threshold.current !== undefined) parts.push(`Arus: ${threshold.current}A`);
    return parts.join(', ') || '–';
}

/** Tambahkan node ke dropdown filter alert jika belum ada */
function _addNodeToAlertFilter(nodeId) {
    const select = document.getElementById('alert-node-filter');
    if (!select) return;
    const exists = Array.from(select.options).some(opt => opt.value === nodeId);
    if (!exists) {
        const opt = document.createElement('option');
        opt.value = nodeId;
        opt.textContent = `Lampu ${nodeId}`;
        select.appendChild(opt);
    }
}

/** Update kartu statistik di bagian atas halaman alert */
function _updateAlertStats() {
    const active = alertsData.filter(a => !a.isDismissed);
    const unread = active.filter(a => !a.isRead).length;
    const critical = active.filter(a => a.severity === 'critical').length;

    const totalEl = document.getElementById('stat-total');
    const unreadEl = document.getElementById('stat-unread');
    const criticalEl = document.getElementById('stat-critical');

    if (totalEl) totalEl.textContent = active.length;
    if (unreadEl) unreadEl.textContent = unread;
    if (criticalEl) criticalEl.textContent = critical;
}

// ============================================================
//  ALERT INBOX — Inisialisasi: Fetch Data dari DB
// ============================================================

/**
 * Ambil history alerts dari database via Node-RED API.
 * Dipanggil saat navigasi ke halaman Inbox Alerts.
 */
function fetchAlertsFromDB() {
    const listEl = document.getElementById('alert-list');
    const emptyEl = document.getElementById('alert-empty-state');

    // Tampilkan loading state
    if (listEl) listEl.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 40px;">Memuat data peringatan...</p>';
    if (emptyEl) emptyEl.style.display = 'none';

    fetch(`${API_BASE_URL}/api/alerts-history?limit=100`)
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        })
        .then(rows => {
            // Reset alertsData — hanya isi dari DB, bukan seed
            // Pertahankan alerts dari WebSocket real-time yang mungkin sudah masuk
            // (filter: hanya hapus yang punya id numerik dari DB, biarkan 'alert_ws_*')
            alertsData = alertsData.filter(a => typeof a.id === 'string' && a.id.startsWith('alert_ws_'));

            // Mapping kolom DB ke format alertsData internal
            const levelToSeverity = {
                'critical': 'critical',
                'Critical': 'critical',
                'warning': 'warning',
                'Warning': 'warning',
                'info': 'info',
                'Info': 'info'
            };

            const titleToType = {
                'Lonjakan Tegangan': 'voltage_spike',
                'Penurunan Tegangan': 'voltage_drop',
                'Lonjakan Arus': 'current_spike',
                'Arus Tinggi': 'current_high',
                'Perangkat Offline / Tegangan Low': 'offline',
                'Perangkat Offline': 'offline',
                'Konsumsi Daya Tinggi': 'power_high',
                'Tes Manual': 'manual'
            };

            // Parse threshold_info (e.g. "V: 240V" atau "I: 1.5A") ke object
            function parseThreshold(thresholdInfo) {
                if (!thresholdInfo) return {};
                const result = {};
                const vMatch = thresholdInfo.match(/V:\s*([\d.]+)V/i);
                const iMatch = thresholdInfo.match(/I:\s*([\d.]+)A/i);
                if (vMatch) result.volt = parseFloat(vMatch[1]);
                if (iMatch) result.current = parseFloat(iMatch[1]);
                return result;
            }

            rows.forEach(row => {
                const alertObj = {
                    id: row.id,           // integer dari DB
                    nodeId: row.device_id,
                    severity: levelToSeverity[row.level] || 'info',
                    type: titleToType[row.title] || 'unknown',
                    message: row.message || '',
                    volt: parseFloat(row.volt) || 0,
                    current: parseFloat(row.current) || 0,
                    power: parseFloat(row.power) || 0,
                    threshold: parseThreshold(row.threshold_info),
                    timestamp: new Date(row.created_at),
                    isRead: row.is_read === true || row.is_read === 't' || row.is_read === 'true',
                    isDismissed: false
                };

                alertsData.push(alertObj);
                _addNodeToAlertFilter(alertObj.nodeId);
            });

            updateAlertBadge();
            renderAlertList();
        })
        .catch(err => {
            console.error('Gagal memuat alerts dari DB:', err);
            if (listEl) listEl.innerHTML = '<p style="color: var(--danger); text-align: center; padding: 40px;">⚠ Gagal memuat data peringatan. Periksa koneksi jaringan Anda.</p>';
        });
}

// ============================================================
//  ALERT INBOX — Deteksi Anomali dari WebSocket
//  (Dipasang pada socket.onmessage yang sudah ada di atas,
//   logika ini dipanggil via _checkAndTriggerAlert)
// ============================================================

/**
 * Periksa data perangkat untuk anomali dan buat alert jika perlu.
 * Dipanggil setiap kali data perangkat diperbarui dari WebSocket.
 */
function _checkAndTriggerAlert(deviceId, data) {
    const volt = parseFloat(data.volt) || 0;
    const current = parseFloat(data.current) || 0;
    const power = parseFloat(data.power) || (volt * current);

    // Definisi aturan anomali: [kondisi, severity, type, threshold]
    const rules = [
        { check: volt > 240, severity: 'critical', type: 'voltage_spike', threshold: { volt: 240 } },
        { check: volt < 100 && volt > 0, severity: 'critical', type: 'offline', threshold: { volt: 100 } },
        { check: current > 1.5, severity: 'critical', type: 'current_spike', threshold: { current: 1.5 } },
        { check: volt >= 100 && volt < 200, severity: 'warning', type: 'voltage_drop', threshold: { volt: 200 } },
        { check: current > 1.0 && current <= 1.5, severity: 'warning', type: 'current_high', threshold: { current: 1.0 } },
        { check: power > 350, severity: 'warning', type: 'power_high', threshold: {} }
    ];

    rules.forEach(rule => {
        if (rule.check) {
            const message = generateAlertMessage(rule.type, deviceId, volt, current);
            addAlert({
                nodeId: deviceId,
                severity: rule.severity,
                type: rule.type,
                message: message,
                volt: volt,
                current: current,
                power: parseFloat(power.toFixed(2)),
                threshold: rule.threshold,
                timestamp: new Date(),
                isRead: false,
                isDismissed: false
            });
        }
    });
}

// ============================================================
//  NODE-RED ALERT FORMAT INTEGRATION
// ============================================================
//
// Node-RED Alert Format (via ws/alerts atau ws/telemetry dengan field alert):
// {
//   "id": "L-107",           ← node ID
//   "alert": true,           ← flag untuk memicu pemrosesan alert
//   "alertType": "voltage_spike",
//   "volt": 245.2,
//   "current": 0.85,
//   "power": 208.4,
//   "severity": "critical"   ← opsional, auto-detected jika tidak ada
// }
//
// Pesan WebSocket dengan field alert === true akan langsung memanggil addAlert()
// tanpa melalui logika deteksi otomatis.
// ============================================================

// ============================================================
// WIDGET CHAT AI - terhubung ke POST /api/chat (backend Python -> Gemini,
// tool-calling di-ground ke data Postgres, jawaban akhir di-stream via SSE).
// ============================================================

// Riwayat percakapan sisi klien - dikirim ulang tiap request biar model ingat
// konteks sebelumnya (API di baliknya stateless, sama seperti /api/login dkk).
let aiChatHistory = [];

function setAiChatStatus(text) {
    const el = document.getElementById('ai-chat-status');
    if (el) el.textContent = text;
}

function toggleAiChat() {
    const panel = document.getElementById('ai-chat-panel');
    const fab = document.getElementById('ai-chat-fab');
    if (!panel || !fab) return;

    const isOpen = panel.classList.toggle('is-open');
    fab.classList.toggle('is-open', isOpen);
    fab.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    panel.setAttribute('aria-hidden', isOpen ? 'false' : 'true');

    if (isOpen) {
        const input = document.getElementById('ai-chat-input');
        if (input) setTimeout(() => input.focus(), 50);
    }
}

function closeAiChat() {
    const panel = document.getElementById('ai-chat-panel');
    const fab = document.getElementById('ai-chat-fab');
    if (!panel || !fab) return;
    panel.classList.remove('is-open');
    fab.classList.remove('is-open');
    fab.setAttribute('aria-expanded', 'false');
    panel.setAttribute('aria-hidden', 'true');
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const panel = document.getElementById('ai-chat-panel');
        if (panel && panel.classList.contains('is-open')) closeAiChat();
    }
});

function appendAiChatBubble(role, text) {
    const list = document.getElementById('ai-chat-messages');
    if (!list) return null;
    const bubble = document.createElement('div');
    bubble.className = `ai-chat-bubble ai-chat-bubble-${role}`;
    bubble.textContent = text;
    list.appendChild(bubble);
    list.scrollTop = list.scrollHeight;
    return bubble;
}

async function handleAiChatSubmit(event) {
    event.preventDefault();
    const input = document.getElementById('ai-chat-input');
    const sendBtn = document.querySelector('.ai-chat-send-btn');
    if (!input) return;

    const message = input.value.trim();
    if (!message) return;

    appendAiChatBubble('user', message);
    input.value = '';
    input.disabled = true;
    if (sendBtn) sendBtn.disabled = true;
    setAiChatStatus('Mengetik...');

    const assistantBubble = appendAiChatBubble('assistant', '...');
    let firstChunkReceived = false;
    let fullText = '';

    try {
        const res = await fetch(`${API_BASE_URL}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, history: aiChatHistory }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            assistantBubble.textContent = err.error || `Asisten AI sedang bermasalah (HTTP ${res.status}).`;
            setAiChatStatus('Error');
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        const list = document.getElementById('ai-chat-messages');

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop(); // baris terakhir mungkin belum lengkap - simpan buat chunk berikutnya

            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed.startsWith('data:')) continue;
                const dataStr = trimmed.slice(5).trim();
                if (!dataStr || dataStr === '[DONE]') continue;

                let parsed;
                try {
                    parsed = JSON.parse(dataStr);
                } catch (e) {
                    continue; // baris SSE terpotong di batas chunk, lewati
                }

                if (parsed.error) {
                    fullText += (fullText ? '\n' : '') + `[${parsed.error}]`;
                } else {
                    const delta = parsed.choices?.[0]?.delta?.content;
                    if (delta) fullText += delta;
                }

                if (!firstChunkReceived && fullText) {
                    firstChunkReceived = true;
                }
                assistantBubble.textContent = fullText || '...';
                if (list) list.scrollTop = list.scrollHeight;
            }
        }

        if (!fullText) assistantBubble.textContent = '(tidak ada balasan dari model)';
        aiChatHistory.push({ role: 'user', content: message });
        aiChatHistory.push({ role: 'assistant', content: fullText });
        setAiChatStatus('Aktif');
    } catch (err) {
        console.error('[AI Chat] Gagal terhubung ke backend:', err);
        assistantBubble.textContent = 'Tidak bisa menghubungi server. Periksa koneksi jaringan.';
        setAiChatStatus('Error');
    } finally {
        input.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
        input.focus();
    }
}
