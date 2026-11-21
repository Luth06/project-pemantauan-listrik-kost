# Smart Energy Monitoring Kos (IoT)

Sistem pemantauan konsumsi listrik per kamar kos secara *real-time* menggunakan ESP32 + PZEM-004T v3, MQTT (Mosquitto), FastAPI, PostgreSQL + TimescaleDB, dan Dashboard Web.

## Peringatan Keselamatan (AC 220V)
Modul PZEM-004T terhubung langsung ke tegangan listrik AC 220V yang mematikan. Wajib gunakan MCB pelindung, isolasi kabel yang rapat, *enclosure* tertutup non-konduktif, dan lakukan pemasangan dalam kondisi MCB OFF oleh teknisi berkompeten.

## Cara Menjalankan Cepat (Lokal)

1. Salin `.env.example` menjadi `.env` dan sesuaikan password:
   ```bash
   cp .env.example .env
   ```

2. Buat file password Mosquitto (`docker/mosquitto/pwfile`):
   ```bash
   touch docker/mosquitto/pwfile
   docker run --rm -v $(pwd)/docker/mosquitto:/mosquitto/config eclipse-mosquitto:2.0 \
     mosquitto_passwd -b /mosquitto/config/pwfile iot_backend GantiPasswordMqtt123!
   ```

3. Jalankan seluruh layanan dengan Docker Compose:
   ```bash
   docker compose up -d --build
   ```

4. Uji aliran data menggunakan simulator (tanpa hardware ESP32):
   ```bash
   pip install aiomqtt
   python simulator/mqtt_simulator.py
   ```

5. Akses aplikasi:
   - Dashboard Web: `http://localhost:3000`
   - Dokumentasi REST API (Swagger): `http://localhost:8000/docs`
