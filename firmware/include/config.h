#pragma once

// Konfigurasi Wi-Fi & MQTT (Jangan di-commit ke repositori publik)
#define WIFI_SSID       "NAMA_WIFI_KOS"
#define WIFI_PASS       "PASSWORD_WIFI_KOS"

#define MQTT_BROKER     "192.168.1.100"
#define MQTT_PORT       1883
#define MQTT_USER       "iot_node"
#define MQTT_PASS       "GantiPasswordMqtt123!"

#define KOS_ID          "kos_01"
#define KAMAR_ID        "kamar_01"

// Pin Hardware
#define PZEM_RX_PIN     16
#define PZEM_TX_PIN     17
#define RELAY_PIN       26  // Aktif HIGH/LOW sesuai modul relay

// Interval (ms)
#define PUBLISH_INTERVAL_MS   5000
#define NVS_SAVE_INTERVAL_MS  300000  // Simpan ke flash tiap 5 menit (cegah wear)
#define NVS_KWH_THRESHOLD     0.05f   // Atau saat naik 0.05 kWh
#define RING_BUFFER_SIZE      60      // Simpan hingga 5 menit data offline (60 x 5 dtk)
