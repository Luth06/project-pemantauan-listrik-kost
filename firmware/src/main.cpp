#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <PZEM004Tv30.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <time.h>
#include "config.h"

HardwareSerial pzemSerial(2);
PZEM004Tv30 pzem(pzemSerial, PZEM_RX_PIN, PZEM_TX_PIN);
WiFiClient espClient;
PubSubClient mqtt(espClient);
Preferences prefs;

struct Telemetry {
  uint32_t ts;
  uint32_t seq;
  float v, i, p, pf, freq, e_kwh;
  int32_t rssi;
};

Telemetry ringBuf[RING_BUFFER_SIZE];
int bufHead = 0, bufCount = 0;

uint32_t seqCounter = 0;
float savedKwhOffset = 0.0f;
float lastSavedKwh = 0.0f;

unsigned long lastPublishMs = 0;
unsigned long lastNvsSaveMs = 0;
unsigned long lastReconnectMs = 0;
unsigned long reconnectDelayMs = 1000; // Exponential backoff mulai 1 detik

String topicEnergi = String("kos/") + KOS_ID + "/kamar/" + KAMAR_ID + "/energi";
String topicStatus = String("kos/") + KOS_ID + "/kamar/" + KAMAR_ID + "/status";
String topicCmd    = String("kos/") + KOS_ID + "/kamar/" + KAMAR_ID + "/cmd";

void pushBuffer(const Telemetry &t) {
  int idx = (bufHead + bufCount) % RING_BUFFER_SIZE;
  ringBuf[idx] = t;
  if (bufCount < RING_BUFFER_SIZE) {
    bufCount++;
  } else {
    bufHead = (bufHead + 1) % RING_BUFFER_SIZE;
  }
}

bool publishTelemetry(const Telemetry &t) {
  StaticJsonDocument<256> doc;
  doc["ts"]    = t.ts;
  doc["seq"]   = t.seq;
  doc["v"]     = round(t.v * 10.0) / 10.0;
  doc["i"]     = round(t.i * 100.0) / 100.0;
  doc["p"]     = round(t.p * 10.0) / 10.0;
  doc["pf"]    = round(t.pf * 100.0) / 100.0;
  doc["freq"]  = round(t.freq * 10.0) / 10.0;
  doc["e_kwh"] = round(t.e_kwh * 1000.0) / 1000.0;
  doc["rssi"]  = t.rssi;

  char payload[256];
  serializeJson(doc, payload);
  return mqtt.publish(topicEnergi.c_str(), payload, false);
}

void flushBuffer() {
  while (bufCount > 0 && mqtt.connected()) {
    if (publishTelemetry(ringBuf[bufHead])) {
      bufHead = (bufHead + 1) % RING_BUFFER_SIZE;
      bufCount--;
    } else {
      break;
    }
  }
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  if (String(topic) == topicCmd) {
    if (msg == "RELAY_OFF") digitalWrite(RELAY_PIN, LOW);
    else if (msg == "RELAY_ON") digitalWrite(RELAY_PIN, HIGH);
  }
}

void maintainConnections(unsigned long now) {
  if (WiFi.status() != WL_CONNECTED) {
    if (now - lastReconnectMs >= reconnectDelayMs) {
      lastReconnectMs = now;
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      reconnectDelayMs = min(reconnectDelayMs * 2, 60000UL);
    }
    return;
  }

  if (!mqtt.connected()) {
    if (now - lastReconnectMs >= reconnectDelayMs) {
      lastReconnectMs = now;
      String clientId = String(KOS_ID) + "_" + KAMAR_ID;
      if (mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASS,
                       topicStatus.c_str(), 1, true, "offline")) {
        mqtt.publish(topicStatus.c_str(), "online", true);
        mqtt.subscribe(topicCmd.c_str(), 1);
        reconnectDelayMs = 1000;
        flushBuffer();
      } else {
        reconnectDelayMs = min(reconnectDelayMs * 2, 60000UL);
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, HIGH);

  prefs.begin("energy_nvs", false);
  savedKwhOffset = prefs.getFloat("kwh_total", 0.0f);
  lastSavedKwh = savedKwhOffset;

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  configTime(0, 0, "pool.ntp.org", "time.google.com");

  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
}

void loop() {
  unsigned long now = millis();
  maintainConnections(now);
  mqtt.loop();

  if (now - lastPublishMs >= PUBLISH_INTERVAL_MS) {
    lastPublishMs = now;

    float v = pzem.voltage();
    float i = pzem.current();
    float p = pzem.power();
    float e = pzem.energy();
    float f = pzem.frequency();
    float pf = pzem.pf();

    if (isnan(v) || isnan(p) || isnan(e)) return;

    float totalKwh = (e >= savedKwhOffset) ? e : (savedKwhOffset + e);

    Telemetry t;
    t.ts    = (uint32_t)time(nullptr);
    t.seq   = ++seqCounter;
    t.v     = v;
    t.i     = i;
    t.p     = p;
    t.pf    = pf;
    t.freq  = f;
    t.e_kwh = totalKwh;
    t.rssi  = WiFi.RSSI();

    if (mqtt.connected()) {
      if (!publishTelemetry(t)) pushBuffer(t);
    } else {
      pushBuffer(t);
    }

    if ((totalKwh - lastSavedKwh >= NVS_KWH_THRESHOLD) ||
        (now - lastNvsSaveMs >= NVS_SAVE_INTERVAL_MS && totalKwh > lastSavedKwh)) {
      prefs.putFloat("kwh_total", totalKwh);
      lastSavedKwh = totalKwh;
      lastNvsSaveMs = now;
    }
  }
}
