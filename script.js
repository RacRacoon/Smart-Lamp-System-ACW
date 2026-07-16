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
                            ldrMode: incomingData.ldrMode || false,
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
                            volt: [220, 220, 220, 220, 220, 220, 220],
                            ampere: [0, 0, 0, 0, 0, 0, 0],
                            watt: [0, 0, 0, 0, 0, 0, 0]
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

                // Jalankan sinkronisasi halaman jika perangkat ini sedang aktif dibuka
                const currentActiveDevice = document.getElementById("current-device-id")?.innerText;
                if (currentActiveDevice === deviceId) {
                    switchDevice(deviceId); // Fungsi sinkronisasi multidimensi kita
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
                ldrMode: false,
                schedules: [
                    { time: "17:30", dim: 6, cct: 30 },
                    { time: "23:00", dim: 4, cct: 80 },
                    { time: "03:30", dim: 8, cct: 100 }
                ]
            };
        }
    }
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
        const selector = document.getElementById("device-selector");
        if (selector) selector.value = key;
        switchDevice(key);
    });

    markers[key] = marker;
}

// Jalankan inisialisasi aplikasi saat halaman web selesai dimuat (DOM Ready)
document.addEventListener("DOMContentLoaded", () => {
    initMap(); // Menginisialisasi objek peta terlebih dahulu
    
    // Ambil data terbaru dari database PostgreSQL melalui API Node-RED yang baru dibuat
    fetch('http://localhost:1880/api/devices-latest')
        .then(response => response.json())
        .then(dbData => {
            console.log("Memuat data node dari PostgreSQL:", dbData);
            
            // Masukkan data dari database ke memory frontend secara dinamis
            dbData.forEach(node => {
                const deviceId = node.id;
                
                // Masukkan data log terbaru ke struktur frontend
                devicesData[deviceId] = {
                    id: deviceId,
                    sector: node.sector,
                    health: node.health || "Healthy",
                    uptime: parseInt(node.uptime) || 0,
                    volt: parseFloat(node.volt) || 0,
                    current: parseFloat(node.current) || 0,
                    power: parseFloat(node.power) || 0,
                    lat: parseFloat(node.lat),
                    lng: parseFloat(node.lng),
                    alerts: node.health === "Healthy" ? 0 : 1
                };

                // Daftarkan ke pengaturan default jika belum ada
                if (!nodeSettings[deviceId]) {
                    nodeSettings[deviceId] = {
                        ldrMode: false,
                        schedules: [
                            { time: "17:30", dim: 6, cct: 30 },
                            { time: "23:00", dim: 4, cct: 80 },
                            { time: "03:30", dim: 8, cct: 100 }
                        ]
                    };
                }

                // Masukkan opsi dropdown dinamis (Termasuk L-107)
                addDeviceToDropdowns(deviceId, node.sector);

                // Gambar pinpoint di peta secara otomatis
                addNewMapMarker(devicesData[deviceId]);
            });

            // Set default device setelah data terisi (misal L-102 atau node pertama yang ada)
            const defaultDevice = devicesData["L-102"] ? "L-102" : Object.keys(devicesData)[0];
            if (defaultDevice) {
                switchDevice(defaultDevice);
            }
            
            // Setelah data awal dari database masuk, baru buka koneksi real-time WebSocket
            connectWebSocket();
        })
        .catch(err => {
            console.error("Gagal memuat data awal dari database, menjalankan mode lokal standalone:", err);
            // Fallback jika API backend mati agar web tidak crash
            switchDevice("L-102");
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
    "Sektor 1 (Jalan Tunjungan)": { ldrMode: false, schedules: [{ time: "17:30", dim: 6, cct: 30 }, { time: "23:00", dim: 4, cct: 80 }, { time: "03:30", dim: 8, cct: 100 }] },
    "Sektor 2 (Kertajaya - Depan ITS)": { ldrMode: true, schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] }
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

// Fungsi pembantu untuk mempopulasikan pengaturan LDR & Jadwal ke Form
function loadSettingsToUI(settings) {
    if (!settings) return;

    const ldrToggle = document.getElementById("ldr-toggle");
    if (ldrToggle) ldrToggle.checked = settings.ldrMode;

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
            const selector = document.getElementById("device-selector");
            if (selector) selector.value = key;
            switchDevice(key);
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

    const alertBadgeEl = document.getElementById("alert-badge");
    if (alertBadgeEl) alertBadgeEl.innerText = data.alerts;

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

    // 2. ISI DATA KE PANEL DETIL PETA (Berdasarkan nodeSettings)
    const settings = nodeSettings[deviceId];
    if (settings) {
        const panelNodeId = document.getElementById("panel-node-id");
        if (panelNodeId) panelNodeId.innerText = deviceId;

        const ldrBadge = document.getElementById("panel-ldr-status");
        if (ldrBadge) {
            if (settings.ldrMode) {
                ldrBadge.innerText = "Aktif (Otomatis Mati Siang Hari)";
                ldrBadge.className = "info-badge active-ldr";
            } else {
                ldrBadge.innerText = "Non-Aktif (Manual/Schedule)";
                ldrBadge.className = "info-badge";
            }
        }

        // Update jadwal fase rtc di panel peta jika elemennya ada
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
    "L-101": { ldrMode: false, schedules: [{ time: "17:30", dim: 6, cct: 30 }, { time: "23:00", dim: 4, cct: 80 }, { time: "03:30", dim: 8, cct: 100 }] },
    "L-102": { ldrMode: true, schedules: [{ time: "17:30", dim: 7, cct: 40 }, { time: "22:30", dim: 5, cct: 70 }, { time: "04:00", dim: 9, cct: 90 }] },
    "L-103": { ldrMode: false, schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] },
    "L-104": { ldrMode: true, schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] },
    "L-105": { ldrMode: false, schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] },
    "L-106": { ldrMode: true, schedules: [{ time: "18:00", dim: 5, cct: 50 }, { time: "00:00", dim: 3, cct: 80 }, { time: "03:00", dim: 7, cct: 100 }] }
};

// FUNGSI NAVIGASI TAB HALAMAN (Sudah disatukan & dibersihkan dari duplikasi)
function navigateTo(pageId, element) {
    // Sembunyikan semua halaman
    document.getElementById("page-dashboard").style.display = "none";
    document.getElementById("page-manage").style.display = "none";
    document.getElementById("page-telemetry").style.display = "none";

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

        // Ambil ID perangkat yang aktif saat ini untuk tampilan default grafik
        const activeId = document.getElementById("current-device-id").innerText || "L-102";
        document.getElementById("telemetry-device-selector").value = activeId;

        // Render grafik seketika
        renderTelemetryChart(activeId);
    }

    element.classList.add("active");
}

// Mengisi Form Input Manage Node dengan data lampu yang dipilih
function loadNodeSettingsToUI(deviceId) {
    loadSettingsToUI(nodeSettings[deviceId]);
}

// Menyimpan konfigurasi parameter form menjadi JSON payload (Mendukung Sektor & Node)
function saveNodeSettings() {
    const currentDeviceId = document.getElementById("current-device-id").innerText;
    const configModeEl = document.querySelector('input[name="config-mode"]:checked');
    const configMode = configModeEl ? configModeEl.value : "node";
    const applyAll = document.getElementById("apply-all-toggle").checked;

    // Kumpulkan data mutakhir dari form input DOM HTML
    const updatedSchedules = [];
    for (let i = 1; i <= 3; i++) {
        updatedSchedules.push({
            time: document.getElementById(`sched-time-${i}`).value,
            dim: parseInt(document.getElementById(`sched-dim-${i}`).value),
            cct: parseInt(document.getElementById(`sched-cct-${i}`).value)
        });
    }
    const isLdrMode = document.getElementById("ldr-toggle").checked;

    if (configMode === "sector") {
        const selectedSector = document.getElementById("sector-selector-input").value;

        if (sectorSettings[selectedSector]) {
            sectorSettings[selectedSector].ldrMode = isLdrMode;
            sectorSettings[selectedSector].schedules = JSON.parse(JSON.stringify(updatedSchedules));
        }

        if (applyAll) {
            Object.keys(devicesData).forEach(key => {
                if (devicesData[key].sector === selectedSector) {
                    if (nodeSettings[key]) {
                        nodeSettings[key].ldrMode = isLdrMode;
                        nodeSettings[key].schedules = JSON.parse(JSON.stringify(updatedSchedules));
                    }
                }
            });
            console.log(`BROADCAST SEKTOR: Mengirim konfigurasi ke seluruh Node di ${selectedSector}`);
            alert(`Sukses! Semua node di ${selectedSector} berhasil disinkronisasikan.`);
        } else {
            alert(`Sukses! Profil konfigurasi untuk ${selectedSector} telah diperbarui.`);
        }
    } else {
        // Logika Mode Per-Node
        if (nodeSettings[currentDeviceId]) {
            nodeSettings[currentDeviceId].ldrMode = isLdrMode;
            nodeSettings[currentDeviceId].schedules = updatedSchedules;
        }

        if (applyAll) {
            Object.keys(nodeSettings).forEach(key => {
                nodeSettings[key].ldrMode = isLdrMode;
                nodeSettings[key].schedules = JSON.parse(JSON.stringify(updatedSchedules));
            });
            alert("Sukses! Konfigurasi global diterapkan ke SELURUH lampu.");
        } else {
            alert(`Sukses! Parameter Manajemen untuk Node ${currentDeviceId} berhasil disimpan.`);
        }
    }
    document.getElementById("apply-all-toggle").checked = false;
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

// INISIALISASI / UPDATE GRAFIK CHART.JS
function renderTelemetryChart(deviceId) {
    const dataSet = telemetryHistory[deviceId];
    if (!dataSet) return;

    const avgVoltVal = (dataSet.volt.reduce((a, b) => a + b, 0) / dataSet.volt.length).toFixed(1);
    const avgAmpVal = (dataSet.ampere.reduce((a, b) => a + b, 0) / dataSet.ampere.length).toFixed(2);
    const avgWattVal = (dataSet.watt.reduce((a, b) => a + b, 0) / dataSet.watt.length).toFixed(1);

    document.getElementById("avg-volt").innerText = `${avgVoltVal} V`;
    document.getElementById("avg-amp").innerText = `${avgAmpVal} A`;
    document.getElementById("avg-watt").innerText = `${avgWattVal} W`;

    const ctx = document.getElementById('telemetryChart').getContext('2d');

    if (telemetryChartInstance) {
        telemetryChartInstance.destroy();
    }

    telemetryChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dataSet.labels,
            datasets: [
                {
                    label: 'Tegangan (Volt)',
                    data: dataSet.volt,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    yAxisID: 'y-volt',
                    tension: 0.3,
                    fill: true
                },
                {
                    label: 'Arus (Ampere)',
                    data: dataSet.ampere,
                    borderColor: '#10b981',
                    backgroundColor: 'transparent',
                    yAxisID: 'y-ampere',
                    tension: 0.3
                },
                {
                    label: 'Daya Aktif (Watt)',
                    data: dataSet.watt,
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
                    max: 240
                },
                'y-ampere': {
                    type: 'linear',
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#10b981' },
                    title: { display: true, text: 'Arus (A)', color: '#10b981' },
                    min: 0,
                    max: 1.5
                },
                'y-watt': {
                    type: 'linear',
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#f59e0b' },
                    title: { display: true, text: 'Daya (W)', color: '#f59e0b' },
                    min: 0,
                    max: 250
                }
            }
        }
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