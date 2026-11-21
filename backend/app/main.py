import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict, Set

import aiomqtt
import asyncpg
import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DATABASE_URL = os.getenv("DATABASE_URL")
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_OWNER_CHAT_ID", "")

app = FastAPI(title="Smart Energy Monitoring Kos API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db_pool: asyncpg.Pool = None
ws_clients: Dict[str, Set[WebSocket]] = {}


class TopUpRequest(BaseModel):
    tambah_kwh: float


async def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message})
        except Exception:
            pass


async def broadcast_ws(kamar_id: str, data: dict):
    clients = ws_clients.get(kamar_id, set()) | ws_clients.get("all", set())
    dead = []
    for ws in clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        for group in ws_clients.values():
            group.discard(ws)


async def process_energy_message(kamar_id: str, payload: dict):
    ts_epoch = payload.get("ts", int(datetime.now(timezone.utc).timestamp()))
    # Fallback ke waktu server jika NTP ESP32 belum sinkron (< tahun 2023)
    if ts_epoch < 1700000000:
        ts = datetime.now(timezone.utc)
    else:
        ts = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)

    seq = int(payload.get("seq", 0))
    v = float(payload["v"])
    i = float(payload["i"])
    p = float(payload["p"])
    pf = float(payload["pf"])
    freq = float(payload["freq"])
    e_kwh = float(payload["e_kwh"])
    rssi = int(payload.get("rssi", 0))

    async with db_pool.acquire() as conn:
        prev = await conn.fetchrow(
            "SELECT ts, e_kwh FROM pengukuran WHERE kamar_id=$1 ORDER BY ts DESC LIMIT 1",
            kamar_id,
        )
        if prev is None:
            delta_kwh = 0.0
        elif e_kwh >= prev["e_kwh"]:
            delta_kwh = e_kwh - prev["e_kwh"]
        else:
            # Counter reset terdeteksi -> fallback ke Riemann Sum (P * dt)
            dt_sec = max((ts - prev["ts"]).total_seconds(), 0)
            delta_kwh = (p * dt_sec) / 3_600_000.0 if dt_sec <= 600 else 0.0

        # Simpan idempoten (abaikan jika ts+seq sudah ada)
        inserted = await conn.fetchval(
            """
            INSERT INTO pengukuran (ts, kamar_id, seq, v, i, p, pf, freq, e_kwh, delta_kwh, rssi)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (kamar_id, ts, seq) DO NOTHING
            RETURNING 1
            """,
            ts, kamar_id, seq, v, i, p, pf, freq, e_kwh, delta_kwh, rssi,
        )

        if inserted and delta_kwh > 0:
            sisa = await conn.fetchval(
                """
                UPDATE token_kuota
                SET kwh_sisa = GREATEST(kwh_sisa - $1, 0)
                WHERE id = (SELECT id FROM token_kuota WHERE kamar_id=$2 ORDER BY dibuat_pada DESC LIMIT 1)
                RETURNING kwh_sisa
                """,
                delta_kwh, kamar_id,
            )
            if sisa is not None and sisa <= 1.0:
                await send_telegram(f"Peringatan: Sisa kuota token {kamar_id} tinggal {sisa:.2f} kWh!")

        await conn.execute(
            "UPDATE kamar SET status_online=TRUE, last_seen=NOW() WHERE id=$1", kamar_id
        )

    await broadcast_ws(kamar_id, {"kamar_id": kamar_id, **payload, "delta_kwh": delta_kwh})


async def mqtt_listener():
    while True:
        try:
            async with aiomqtt.Client(
                hostname=MQTT_HOST, port=MQTT_PORT, username=MQTT_USER, password=MQTT_PASSWORD
            ) as client:
                await client.subscribe("kos/+/kamar/+/energi", qos=1)
                await client.subscribe("kos/+/kamar/+/status", qos=1)
                async for message in client.messages:
                    parts = str(message.topic).split("/")
                    if len(parts) != 5:
                        continue
                    kamar_id, msg_type = parts[3], parts[4]
                    if msg_type == "energi":
                        try:
                            data = json.loads(message.payload.decode())
                            await process_energy_message(kamar_id, data)
                        except Exception:
                            continue
                    elif msg_type == "status":
                        is_online = message.payload.decode().strip().lower() == "online"
                        async with db_pool.acquire() as conn:
                            await conn.execute(
                                "UPDATE kamar SET status_online=$1, last_seen=NOW() WHERE id=$2",
                                is_online, kamar_id,
                            )
        except Exception:
            await asyncio.sleep(5)


@app.on_event("startup")
async def startup():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=20)
    asyncio.create_task(mqtt_listener())


@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()


@app.get("/kamar")
async def list_kamar():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM kamar ORDER BY id")
        return [dict(r) for r in rows]


@app.get("/kamar/{kamar_id}/realtime")
async def get_realtime(kamar_id: str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM pengukuran WHERE kamar_id=$1 ORDER BY ts DESC LIMIT 1", kamar_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Belum ada data sensor")
        return dict(row)


@app.get("/kamar/{kamar_id}/tagihan")
async def get_tagihan(kamar_id: str, bulan: str):
    async with db_pool.acquire() as conn:
        kamar = await conn.fetchrow("SELECT tarif_per_kwh FROM kamar WHERE id=$1", kamar_id)
        if not kamar:
            raise HTTPException(status_code=404, detail="Kamar tidak ditemukan")
        total_kwh = await conn.fetchval(
            """
            SELECT COALESCE(SUM(delta_kwh), 0)
            FROM pengukuran
            WHERE kamar_id=$1 AND to_char(ts, 'YYYY-MM') = $2
            """,
            kamar_id, bulan,
        )
        biaya_rp = round(float(total_kwh) * float(kamar["tarif_per_kwh"]))
        return {
            "kamar_id": kamar_id,
            "bulan": bulan,
            "total_kwh": round(float(total_kwh), 3),
            "tarif_per_kwh": float(kamar["tarif_per_kwh"]),
            "estimasi_biaya_rp": biaya_rp,
        }


@app.post("/kamar/{kamar_id}/topup")
async def topup_kuota(kamar_id: str, body: TopUpRequest):
    if body.tambah_kwh <= 0:
        raise HTTPException(status_code=400, detail="Jumlah kWh harus positif")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO token_kuota (kamar_id, kwh_awal, kwh_sisa)
            VALUES ($1, $2, $2) RETURNING *
            """,
            kamar_id, body.tambah_kwh,
        )
        return dict(row)


@app.websocket("/ws/kamar/{kamar_id}")
async def ws_kamar(websocket: WebSocket, kamar_id: str):
    await websocket.accept()
    ws_clients.setdefault(kamar_id, set()).add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.get(kamar_id, set()).discard(websocket)
