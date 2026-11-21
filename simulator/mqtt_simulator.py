import asyncio
import json
import random
import sys
import time
import aiomqtt

# Wajib untuk Windows (terutama Python 3.12 - 3.14) agar aiomqtt bisa berjalan
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
MQTT_USER = "iot_backend"
MQTT_PASS = "GantiPasswordMqtt123!"
ROOMS = ["kamar_01", "kamar_02"]

async def main():
    kwh = {r: 10.0 for r in ROOMS}
    seq = {r: 0 for r in ROOMS}
    async with aiomqtt.Client(MQTT_HOST, MQTT_PORT, username=MQTT_USER, password=MQTT_PASS) as client:
        for r in ROOMS:
            await client.publish(f"kos/kos_01/kamar/{r}/status", "online", qos=1, retain=True)
        while True:
            for r in ROOMS:
                p = random.uniform(80.0, 450.0)
                v = random.uniform(218.0, 224.0)
                pf = random.uniform(0.85, 0.98)
                i = p / (v * pf)
                kwh[r] += (p * 5.0) / 3_600_000.0
                seq[r] += 1
                payload = {
                    "ts": int(time.time()), "seq": seq[r],
                    "v": round(v, 1), "i": round(i, 2), "p": round(p, 1),
                    "pf": round(pf, 2), "freq": 50.0,
                    "e_kwh": round(kwh[r], 4), "rssi": random.randint(-75, -50)
                }
                await client.publish(f"kos/kos_01/kamar/{r}/energi", json.dumps(payload), qos=1)
                print(f"Sent {r}: {payload['p']}W | {payload['e_kwh']} kWh")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())