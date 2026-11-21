CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS pengguna (
    id SERIAL PRIMARY KEY,
    nama VARCHAR(100) NOT NULL,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    peran VARCHAR(20) NOT NULL CHECK (peran IN ('pemilik', 'penghuni')),
    telegram_chat_id VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS kamar (
    id VARCHAR(50) PRIMARY KEY,
    kos_id VARCHAR(50) NOT NULL DEFAULT 'kos_01',
    nama VARCHAR(100) NOT NULL,
    penghuni_id INT REFERENCES pengguna(id) ON DELETE SET NULL,
    tarif_per_kwh NUMERIC(10, 2) NOT NULL DEFAULT 1444.70,
    batas_harian_kwh NUMERIC(10, 3) NOT NULL DEFAULT 5.000,
    status_online BOOLEAN NOT NULL DEFAULT FALSE,
    last_seen TIMESTAMPTZ,
    aktif BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS pengukuran (
    ts TIMESTAMPTZ NOT NULL,
    kamar_id VARCHAR(50) NOT NULL REFERENCES kamar(id),
    seq BIGINT NOT NULL,
    v DOUBLE PRECISION NOT NULL,
    i DOUBLE PRECISION NOT NULL,
    p DOUBLE PRECISION NOT NULL,
    pf DOUBLE PRECISION NOT NULL,
    freq DOUBLE PRECISION NOT NULL,
    e_kwh DOUBLE PRECISION NOT NULL,
    delta_kwh DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    rssi INT,
    PRIMARY KEY (kamar_id, ts, seq)
);

SELECT create_hypertable('pengukuran', 'ts', if_not_exists => TRUE);

-- Continuous Aggregate per Jam
CREATE MATERIALIZED VIEW IF NOT EXISTS agregat_jam
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS jam,
    kamar_id,
    SUM(delta_kwh) AS kwh,
    AVG(p) AS p_rata,
    MAX(p) AS p_maks
FROM pengukuran
GROUP BY jam, kamar_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('agregat_jam',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS token_kuota (
    id SERIAL PRIMARY KEY,
    kamar_id VARCHAR(50) NOT NULL REFERENCES kamar(id),
    kwh_awal NUMERIC(10, 3) NOT NULL,
    kwh_sisa NUMERIC(10, 3) NOT NULL,
    dibuat_pada TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifikasi_log (
    id SERIAL PRIMARY KEY,
    kamar_id VARCHAR(50) NOT NULL REFERENCES kamar(id),
    jenis VARCHAR(50) NOT NULL,
    pesan TEXT NOT NULL,
    dikirim_pada TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed data awal untuk pengujian langsung
INSERT INTO kamar (id, kos_id, nama, tarif_per_kwh, batas_harian_kwh)
VALUES
    ('kamar_01', 'kos_01', 'Kamar 01 - Lantai 1', 1444.70, 5.000),
    ('kamar_02', 'kos_01', 'Kamar 02 - Lantai 1', 1444.70, 5.000)
ON CONFLICT (id) DO NOTHING;

INSERT INTO token_kuota (kamar_id, kwh_awal, kwh_sisa)
SELECT 'kamar_01', 50.000, 50.000
WHERE NOT EXISTS (SELECT 1 FROM token_kuota WHERE kamar_id = 'kamar_01');
