#include <Arduino.h>
#include <PZEM004Tv30.h>

// Definisi Pin Komponen
#define RELAY_PIN 47
#define PZEM_RX_PIN 15
#define PZEM_TX_PIN 16

// Inisialisasi PZEM menggunakan Hardware Serial 1 (Serial1)
PZEM004Tv30 pzem(Serial1, PZEM_RX_PIN, PZEM_TX_PIN);

// Variabel Non-blocking Timer untuk Sensor
unsigned long lastPzemRead = 0;
const unsigned long pzemInterval = 100;   // Baca sensor setiap 100 ms

void setup() {
    // Inisialisasi Serial Monitor untuk debugging dan Input Keyboard
    Serial.begin(115200);
    delay(1000); 
    
    // Inisialisasi Pin Relay
    pinMode(RELAY_PIN, OUTPUT);
    digitalWrite(RELAY_PIN, LOW); // Awal: Lampu MATI (Asumsi Relay Active HIGH)
    
    Serial.println("==================================================");
    Serial.println("         ESP32-S3 Keyboard Controlled Socket      ");
    Serial.println("==================================================");
    Serial.println(" KONTROL: Tekan 'Q' untuk NYALA, Tekan 'E' untuk MATI");
    Serial.println("==================================================");
}

void loop() {
    // 1. MEMBACA INPUT KEYBOARD DARI SERIAL MONITOR
    if (Serial.available() > 0) {
        char incomingKey = Serial.read(); // Membaca karakter yang ditekan
        
        // Cek jika tombol Q atau q ditekan
        if (incomingKey == 'Q' || incomingKey == 'q') {
            digitalWrite(RELAY_PIN, HIGH); // Nyalakan Relay
            Serial.println("\n[KEY COMMAND] Menyalakan Lampu (Key: Q)...");
        } 
        // Cek jika tombol E atau e ditekan
        else if (incomingKey == 'E' || incomingKey == 'e') {
            digitalWrite(RELAY_PIN, LOW);  // Matikan Relay
            Serial.println("\n[KEY COMMAND] Memtikan Lampu (Key: E)...");
        }
    }

    // 2. MEMBACA DATA DARI SENSOR PZEM SECARA PERIODIK
    unsigned long currentMillis = millis();
    if (currentMillis - lastPzemRead >= pzemInterval) {
        lastPzemRead = currentMillis;

        Serial.println("\n--- TELEMETRI DATA LISTRIK ---");

        // Membaca Tegangan (Voltage)
        float voltage = pzem.voltage();
        if (!isnan(voltage)) {
            Serial.print("Tegangan      : "); Serial.print(voltage, 1); Serial.println(" V");
        } else {
            Serial.println("[ERROR] Gagal membaca data dari PZEM!");
            return; 
        }

        // Membaca Arus (Current)
        float current = pzem.current();
        if (!isnan(current)) {
            Serial.print("Arus Listrik  : "); Serial.print(current, 3); Serial.println(" A");
        }

        // Membaca Daya Aktif (Power)
        float power = pzem.power();
        if (!isnan(power)) {
            Serial.print("Daya Aktif    : "); Serial.print(power, 1); Serial.println(" W");
        }

        // Membaca Konsumsi Energi Total (Energy)
        float energy = pzem.energy();
        if (!isnan(energy)) {
            Serial.print("Total Energi  : "); Serial.print(energy, 3); Serial.println(" kWh");
        }

        // Membaca Faktor Daya (Power Factor)
        float pf = pzem.pf();
        if (!isnan(pf)) {
            Serial.print("Power Factor  : "); Serial.println(pf, 2);
        }
        
        Serial.println("------------------------------");
    }
}