// 1. Sesuaikan URL dengan IP dan port Node-RED Anda
const NODE_RED_WS_URL = "ws://localhost:1880/ws/telemetry";
let socket;

function connectWebSocket() {
    socket = new WebSocket(NODE_RED_WS_URL);

    socket.onopen = function (event) {
        console.log("Terhubung ke Node-RED secara Real-Time!");
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
                        uptime: incomingData.uptime || 0
                    };

                    // Inisialisasi nodeSettings default untuk node baru ini
                    if (!nodeSettings[deviceId]) {
                        nodeSettings[deviceId] = {
                            schedules: incomingData.schedules || [
                                { time: "17:30", dim: 6, cct: 30 },
                                { time: "23:00", dim: 4, cct: 80 },
                                { time: "03:30", dim: 8, cct: 100 }
                            ]
                        };
                    }

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

                    // Jika user sedang melihat tab Telemetry untuk lampu ini, perbarui grafik secara instant
                    const activeTelDevice = document.getElementById("telemetry-device-selector")?.value;
                    if (activeTelDevice === deviceId) {
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
            }
        } catch (error) {
            console.error("Gagal memproses data dinamis dari Node-RED:", error);
        }
    };

    socket.onclose = function (event) {
        console.log("Koneksi ke Node-RED terputus. Mencoba menghubungkan kembali dalam 5 detik...");
        setTimeout(connectWebSocket, 5000);
    };

    socket.onerror = function (error) {
        console.error("WebSocket Error: ", error);
    };
}

function addDeviceToDropdowns(deviceId, sector) {
    const devSelector = document.getElementById("device-selector");
    const manageSelector = document.getElementById("manage-node-selector");
    const telSelector = document.getElementById("telemetry-device-selector");
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

    if (manageSelector && !optionExists(manageSelector, deviceId)) {
        const opt = document.createElement("option");
        opt.value = deviceId;

        // Ambil hanya bagian sebelum tanda kurung jika ada (misal: "Sektor 2")
        const shortSector = sector.includes("(") ? sector.split("(")[0].trim() : sector;

        opt.textContent = `${deviceId} (${shortSector})`;
        manageSelector.appendChild(opt);
    }

    if (telSelector && !optionExists(telSelector, deviceId)) {
        const opt = document.createElement("option");
        opt.value = deviceId;
        opt.textContent = `Tiang ${deviceId}`;
        telSelector.appendChild(opt);
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
document.addEventListener("DOMContentLoaded", () => {
    initMap();

    fetch('http://localhost:1880/api/devices-latest')
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
                    alerts: node.health === "Healthy" ? 0 : 1
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

                if (!nodeSettings[deviceId]) {
                    nodeSettings[deviceId] = {
                        schedules: [
                            { time: "17:30", dim: 6, cct: 30 },
                            { time: "23:00", dim: 4, cct: 80 },
                            { time: "03:30", dim: 8, cct: 100 }
                        ]
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
        });
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
        alerts: 0
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
        alerts: 1
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
        alerts: 0
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
        alerts: 2
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
        alerts: 0
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
        alerts: 1
    }
};

// State Management Konfigurasi Default Sektor
let sectorSettings = {
    "Sektor 1 (Jalan Tunjungan)": { schedules: [{ time: "17:30", dim: 6, cct: 30 }, { time: "23:00", dim: 4, cct: 80 }, { time: "03:30", dim: 8, cct: 100 }] },
    "Sektor 2 (Kertajaya - Depan ITS)": { schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] }
};

// Fungsi Mengganti Tampilan Form antara Mode Per Node vs Per Sektor
function changeConfigTarget(mode) {
    const nodeSelectorContainer = document.getElementById("node-selector-container");
    const sectorSelectorContainer = document.getElementById("sector-selector-container");
    const globalApplyLabel = document.getElementById("global-apply-label");
    const currentDeviceId = document.getElementById("current-device-id").innerText;

    if (mode === "sector") {
        nodeSelectorContainer.style.display = "none";
        sectorSelectorContainer.style.display = "block";
        globalApplyLabel.innerText = "Terapkan konfigurasi ini ke SEMUA node di dalam Sektor terpilih";

        // Ambil sektor dari perangkat yang saat ini aktif
        const activeSector = devicesData[currentDeviceId].sector;
        document.getElementById("sector-selector-input").value = activeSector;
        loadSectorSettingsToUI(activeSector);
    } else {
        nodeSelectorContainer.style.display = "block";
        sectorSelectorContainer.style.display = "none";
        globalApplyLabel.innerText = "Terapkan konfigurasi ini ke semua lampu secara menyeluruh (Global Apply)";

        loadNodeSettingsToUI(currentDeviceId);
    }
}

// Fungsi pembantu untuk mempopulasikan jadwal ke Form
function loadSettingsToUI(settings) {
    if (!settings) return;

    if (settings.schedules && Array.isArray(settings.schedules)) {
        settings.schedules.forEach((sched, index) => {
            const i = index + 1;
            const timeEl = document.getElementById(`sched-time-${i}`);
            const dimEl = document.getElementById(`sched-dim-${i}`);
            const dimLabelEl = document.getElementById(`sched-dim-label-${i}`);
            const cctEl = document.getElementById(`sched-cct-${i}`);
            const cctLabelEl = document.getElementById(`sched-cct-label-${i}`);

            if (timeEl) timeEl.value = sched.time;
            if (dimEl) dimEl.value = sched.dim;
            if (dimLabelEl) dimLabelEl.innerText = sched.dim;
            if (cctEl) cctEl.value = sched.cct;
            if (cctLabelEl) cctLabelEl.innerText = sched.cct;
        });
    }
}

// Mengisi Form berdasarkan Sektor yang dipilih
function loadSectorSettingsToUI(sectorName) {
    loadSettingsToUI(sectorSettings[sectorName]);
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
        note.innerText = "CRITICAL: Perangkat melampaui batas usia kerja. (Need Maintenance)";
    } else if (uptimeHours >= 8000) {
        container.classList.add("warning-state");
        bar.style.backgroundColor = "var(--warning)";
        note.innerText = "WARNING: Memasuki batas usia pakai optimal.";
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

    // Badge count dikelola oleh updateAlertBadge() dari sistem alert terpusat
    updateAlertBadge();

    // Sinkronisasi dropdown pemilih lampu di Dashboard
    const deviceSelector = document.getElementById("device-selector");
    if (deviceSelector) deviceSelector.value = deviceId;

    // Sinkronisasi dropdown pemilih lampu di Manage Nodes
    const manageNodeSelector = document.getElementById("manage-node-selector");
    if (manageNodeSelector) manageNodeSelector.value = deviceId;

    // Sinkronisasi judul Manage Node aktif
    const manageNodeTitle = document.getElementById("manage-node-title");
    if (manageNodeTitle) manageNodeTitle.innerText = deviceId;

    // Update status indicator
    // Update status indicator secara dinamis berdasarkan threshold uptime
    const statusText = document.getElementById("status-text");
    if (statusText) {
        statusText.className = "status-indicator";

        // Logika Threshold Batas Umur Waktu (Uptime)
        if (data.uptime >= 10000) {
            statusText.innerText = "Need Maintenance"; // Teks disesuaikan logika umur
            statusText.classList.add("status-critical");
        } else if (data.uptime >= 8000) {
            statusText.innerText = "Warning";          // Teks disesuaikan logika umur
            statusText.classList.add("status-warning");
        } else {
            statusText.innerText = "Healthy";          // Teks disesuaikan logika umur
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

    // Sinkronisasi jika tab manage sedang aktif
    const pageManage = document.getElementById("page-manage");
    if (pageManage && pageManage.style.display === "block") {
        if (typeof loadNodeSettingsToUI === "function") {
            loadNodeSettingsToUI(deviceId);
        }
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

// Catatan: Inisialisasi awal dipindahkan ke DOMContentLoaded listener

// Struktur Penyimpanan Pengaturan Konfigurasi Tiap Lampu (State Management)
let nodeSettings = {
    "L-101": { schedules: [{ time: "17:30", dim: 6, cct: 30 }, { time: "23:00", dim: 4, cct: 80 }, { time: "03:30", dim: 8, cct: 100 }] },
    "L-102": { schedules: [{ time: "17:30", dim: 7, cct: 40 }, { time: "22:30", dim: 5, cct: 70 }, { time: "04:00", dim: 9, cct: 90 }] },
    "L-103": { schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] },
    "L-104": { schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] },
    "L-105": { schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] },
    "L-106": { schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] }
};

// FUNGSI NAVIGASI TAB HALAMAN (Sudah disatukan & dibersihkan dari duplikasi)
function navigateTo(pageId, element) {
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
        const currentId = document.getElementById("current-device-id").innerText;

        // Memastikan nama node aktif tersinkronisasi di form judul Manage
        const manageNodeTitle = document.getElementById("manage-node-title");
        if (manageNodeTitle) manageNodeTitle.innerText = currentId;

        // Reset radio button ke "node" setiap kali halaman dibuka kembali
        const radioNode = document.querySelector('input[name="config-mode"][value="node"]');
        if (radioNode) {
            radioNode.checked = true;
            changeConfigTarget("node");
        }
    } else if (pageId === 'telemetry') {
        document.getElementById("page-telemetry").style.display = "block";

        const activeId = document.getElementById("current-device-id").innerText || "L-107";
        const telSelector = document.getElementById("telemetry-device-selector");
        if (telSelector) telSelector.value = activeId;

        // Beri setTimeout agar browser menyelesaikan render display: block terlebih dahulu
        setTimeout(() => {
            renderTelemetryChart(activeId);
        }, 50);
    } else if (pageId === 'alerts') {
        document.getElementById("page-alerts").style.display = "block";
        fetchAlertsFromDB();
    }

    element.classList.add("active");
}

// Mengisi Form Input Manage Node dengan data sektor aktif sebagai sumber kebenaran tunggal
function loadNodeSettingsToUI(deviceId) {
    const data = devicesData[deviceId];
    const activeSector = data ? data.sector : null;
    const settings = activeSector && sectorSettings[activeSector]
        ? sectorSettings[activeSector]
        : null;

    loadSettingsToUI(settings);
}

// Menyimpan konfigurasi jadwal pada state frontend
function saveNodeSettings() {
    const currentDeviceId = document.getElementById("current-device-id").innerText;
    const currentSector = devicesData[currentDeviceId]?.sector || null;

    const updatedSchedules = [];
    for (let i = 1; i <= 3; i++) {
        updatedSchedules.push({
            time: document.getElementById(`sched-time-${i}`).value,
            dim: parseInt(document.getElementById(`sched-dim-${i}`).value),
            cct: parseInt(document.getElementById(`sched-cct-${i}`).value)
        });
    }

    if (currentSector && sectorSettings[currentSector]) {
        sectorSettings[currentSector].schedules = JSON.parse(JSON.stringify(updatedSchedules));
    }

    if (nodeSettings[currentDeviceId]) {
        nodeSettings[currentDeviceId].schedules = JSON.parse(JSON.stringify(updatedSchedules));
    }

    console.log('Konfigurasi jadwal berhasil disimpan di state frontend untuk:', currentSector);
    switchDevice(currentDeviceId);
}

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

let telemetryChartInstance = null;

// INISIALISASI / UPDATE CARD RATA-RATA TELEMETRY
function updateTelemetrySummary(deviceId) {
    const data = telemetryHistory[deviceId];

    // Jika data belum ada/belum selesai di-fetch, set tampilan default ke 0
    if (!data) {
        if (document.getElementById("avg-volt"))
            document.getElementById("avg-volt").innerText = "0 V";
        if (document.getElementById("avg-current"))
            document.getElementById("avg-current").innerText = "0 A";
        if (document.getElementById("avg-power"))
            document.getElementById("avg-power").innerText = "0 W";
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

    // Update elemen HTML
    if (document.getElementById("avg-volt"))
        document.getElementById("avg-volt").innerText = `${calcAvg(voltArr)} V`;
    if (document.getElementById("avg-current"))
        document.getElementById("avg-current").innerText = `${calcAvg(currentArr)} A`;
    if (document.getElementById("avg-power"))
        document.getElementById("avg-power").innerText = `${calcAvg(powerArr)} W`;
}

// FUNGSI MENGGAMBAR/DRAW CHART.JS
function drawChart(deviceId) {
    const dataSet = telemetryHistory[deviceId];
    if (!dataSet) return;

    // Ambil array dengan toleransi nama key
    const labels = dataSet.labels || [];
    const voltArr = dataSet.volt || [];
    const currentArr = dataSet.current || dataSet.ampere || [];
    const powerArr = dataSet.power || dataSet.watt || [];

    const ctx = document.getElementById('telemetryChart').getContext('2d');

    if (telemetryChartInstance) {
        telemetryChartInstance.destroy();
    }

    telemetryChartInstance = new Chart(ctx, {
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
    fetch(`http://localhost:1880/api/telemetry-history?device_id=${deviceId}`)
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

function changeTelemetryDevice(deviceId) {
    renderTelemetryChart(deviceId);
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

function fetchSectorSettings() {
    if (document.getElementById("current-device-id")) {
        switchDevice(document.getElementById("current-device-id").innerText);
    }
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
    // Optimistic UI update
    const alert = alertsData.find(a => a.id === alertId);
    if (alert) {
        alert.isRead = true;
        updateAlertBadge();
        renderAlertList();
    }

    // Persist ke DB
    fetch(`http://localhost:1880/api/alerts/${alertId}/read`, { method: 'PATCH' })
        .catch(err => console.error('Gagal mark-read alert ke DB:', err));
}

/**
 * Tandai semua alert sebagai sudah dibaca — update ke DB.
 */
function markAllRead() {
    alertsData.forEach(a => { a.isRead = true; });
    updateAlertBadge();
    renderAlertList();

    fetch('http://localhost:1880/api/alerts/mark-all-read', { method: 'POST' })
        .catch(err => console.error('Gagal mark-all-read ke DB:', err));
}

/**
 * Hapus satu alert dari tampilan dan DB.
 */
function dismissAlert(alertId) {
    // Optimistic UI update
    const alert = alertsData.find(a => a.id === alertId);
    if (alert) {
        alert.isDismissed = true;
        updateAlertBadge();
        renderAlertList();
    }

    // Hapus dari DB
    fetch(`http://localhost:1880/api/alerts/${alertId}`, { method: 'DELETE' })
        .catch(err => console.error('Gagal hapus alert dari DB:', err));
}

/**
 * Hapus semua alert dari tampilan dan DB.
 */
function clearAllAlerts() {
    alertsData = [];
    alertCooldowns = {};
    updateAlertBadge();
    renderAlertList();

    fetch('http://localhost:1880/api/alerts', { method: 'DELETE' })
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
            return `Node ${nodeId} terdeteksi lonjakan tegangan sebesar ${volt}V, melebihi batas aman 240V. Segera periksa kondisi jaringan listrik.`;
        case 'voltage_drop':
            return `Node ${nodeId} mengalami penurunan tegangan ke ${volt}V (di bawah 200V). Kemungkinan gangguan pasokan daya.`;
        case 'current_spike':
            return `Node ${nodeId} mendeteksi lonjakan arus listrik sebesar ${current}A, melampaui batas kritis 1.5A. Periksa kemungkinan korsleting.`;
        case 'current_high':
            return `Node ${nodeId} mencatat arus tinggi sebesar ${current}A (di atas 1.0A). Pantau secara berkala untuk mencegah kerusakan komponen.`;
        case 'offline':
            return `Node ${nodeId} terdeteksi offline atau tidak bertenaga. Tegangan terbaca ${volt}V, jauh di bawah batas operasional minimum.`;
        case 'power_high':
            const pow = (volt * current).toFixed(1);
            return `Node ${nodeId} mengonsumsi daya melebihi batas normal (${pow}W > 350W). Periksa beban listrik yang terhubung.`;
        default:
            return `Node ${nodeId} mengirimkan sinyal anomali. Mohon lakukan pengecekan langsung di lapangan.`;
    }
}

// ============================================================
//  ALERT INBOX — Helper Internal
// ============================================================

/**
 * Bangun HTML string untuk satu alert card.
 */
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
        ? `<button class="btn-read" onclick="markAlertRead('${alert.id}')">✓ Tandai Dibaca</button>`
        : '';

    return `
    <div class="${cardClass}" id="card-${alert.id}">
        <div class="alert-card-header">
            <div class="alert-card-header-left">
                ${unreadDot}
                <span class="alert-severity-badge ${severityBadgeClass}">${severityLabel}</span>
                <span class="alert-node-id">${alert.nodeId}</span>
                <span style="font-size: 16px;">${typeIcon}</span>
            </div>
            <span class="alert-timestamp">${timestamp}</span>
        </div>
        <p class="alert-message">${alert.message}</p>
        <div class="alert-metrics">
            <div class="alert-metric-item">
                <span class="alert-metric-label">⚡ Tegangan:</span>
                <span class="alert-metric-value ${voltClass}">${alert.volt !== undefined ? alert.volt.toFixed(1) : '–'} V</span>
            </div>
            <div class="alert-metric-item">
                <span class="alert-metric-label">🔌 Arus:</span>
                <span class="alert-metric-value ${currentClass}">${alert.current !== undefined ? alert.current.toFixed(3) : '–'} A</span>
            </div>
            <div class="alert-metric-item">
                <span class="alert-metric-label">💡 Daya:</span>
                <span class="alert-metric-value ${powerClass}">${alert.power !== undefined ? alert.power.toFixed(1) : '–'} W</span>
            </div>
            ${alert.threshold && Object.keys(alert.threshold).length > 0 ? `
            <div class="alert-metric-item">
                <span class="alert-metric-label">📊 Threshold:</span>
                <span class="alert-metric-value">${_formatThreshold(alert.threshold)}</span>
            </div>` : ''}
        </div>
        <div class="alert-footer">
            <span class="alert-type-label">${_formatAlertType(alert.type)}</span>
            <div class="alert-actions">
                ${readBtn}
                <button class="btn-dismiss" onclick="dismissAlert('${alert.id}')">🗑 Hapus</button>
            </div>
        </div>
    </div>`;
}

/** Kembalikan emoji icon berdasarkan tipe alert */
function _getAlertTypeIcon(type) {
    const icons = {
        voltage_spike: '⚡',
        voltage_drop: '📉',
        current_spike: '🔌',
        current_high: '⚠️',
        offline: '📵',
        power_high: '💡'
    };
    return icons[type] || '🔔';
}

/** Format label tipe alert yang lebih mudah dibaca */
function _formatAlertType(type) {
    const labels = {
        voltage_spike: 'Lonjakan Tegangan',
        voltage_drop: 'Penurunan Tegangan',
        current_spike: 'Lonjakan Arus',
        current_high: 'Arus Tinggi',
        offline: 'Perangkat Offline',
        power_high: 'Konsumsi Daya Tinggi'
    };
    return labels[type] || type;
}

/** Format nilai threshold ke string */
function _formatThreshold(threshold) {
    const parts = [];
    if (threshold.volt !== undefined) parts.push(`V: ${threshold.volt}V`);
    if (threshold.current !== undefined) parts.push(`I: ${threshold.current}A`);
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
        opt.textContent = `Node ${nodeId}`;
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
    if (listEl) listEl.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 40px;">Memuat data alerts...</p>';
    if (emptyEl) emptyEl.style.display = 'none';

    fetch('http://localhost:1880/api/alerts-history?limit=100')
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
            if (listEl) listEl.innerHTML = '<p style="color: var(--danger); text-align: center; padding: 40px;">⚠ Gagal memuat data alerts. Periksa koneksi ke Node-RED.</p>';
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
        { check: volt > 240,                severity: 'critical', type: 'voltage_spike',  threshold: { volt: 240 } },
        { check: volt < 100 && volt > 0,    severity: 'critical', type: 'offline',        threshold: { volt: 100 } },
        { check: current > 1.5,             severity: 'critical', type: 'current_spike',  threshold: { current: 1.5 } },
        { check: volt >= 100 && volt < 200, severity: 'warning',  type: 'voltage_drop',   threshold: { volt: 200 } },
        { check: current > 1.0 && current <= 1.5, severity: 'warning', type: 'current_high', threshold: { current: 1.0 } },
        { check: power > 350,               severity: 'warning',  type: 'power_high',     threshold: {} }
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
