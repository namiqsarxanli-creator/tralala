"""Həqiqi serverə 20 eyni vaxtlı oyunçu ilə bütün oyunu keçirir: python tests/load_20.py [port]"""
import asyncio
import json
import random
import statistics
import sys
import time
import urllib.request

import websockets

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from app.seed import SAMPLE  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8020
BASE = f"http://127.0.0.1:{PORT}"
PLAYERS = 20
lags = []


def post(path, body):
    request = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request))


def answer_for(question):
    kind = question["type"]
    if kind in ("choice", "truefalse", "poll"):
        return random.randrange(len(question["options"]))
    if kind == "multi":
        return random.sample(range(len(question["options"])), 2)
    if kind == "order":
        return random.sample(range(len(question["options"])), len(question["options"]))
    if kind == "text":
        return random.choice(["Azərbaycan", "azerbaycan", "Türkiyə"])
    if kind == "cloud":
        return random.choice(["dost", "səs-küy", "qəhvə"])
    return random.randint(int(question["min"]), int(question["max"]))


async def player(pin, number, finished):
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/play/{pin}") as ws:
        await ws.send(json.dumps({"name": f"Oyunçu {number}"}))
        answered = -1
        async for raw in ws:
            view = json.loads(raw)
            if view["phase"] == "question" and view["index"] != answered and not view["answered"]:
                answered = view["index"]
                await asyncio.sleep(random.uniform(0.05, 0.6))
                sent = time.perf_counter()
                await ws.send(json.dumps({"answer": answer_for(view["question"])}))
                while True:
                    view = json.loads(await ws.recv())
                    if view.get("answered") or view["phase"] != "question":
                        lags.append(time.perf_counter() - sent)
                        break
            if view["phase"] == "podium":
                finished.append(view["me"])
                return


async def host(pin):
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/host/{pin}") as ws:
        started = False
        seen = None
        async for raw in ws:
            view = json.loads(raw)
            if view["phase"] == "lobby" and len(view["players"]) == PLAYERS and not started:
                started = True
                await ws.send(json.dumps({"action": "start"}))
            key = (view["phase"], view["index"])
            if view["phase"] in ("reveal", "board") and key != seen:
                seen = key
                await ws.send(json.dumps({"action": "next"}))
            if view["phase"] == "podium":
                return view


async def main():
    quiz_id = post("/api/quizzes", {"title": "Yük sınağı", "questions": SAMPLE})["id"]
    pin = post("/api/rooms", {"quiz_id": quiz_id})["pin"]
    finished = []
    began = time.perf_counter()
    host_task = asyncio.create_task(host(pin))
    await asyncio.sleep(0.2)
    await asyncio.gather(*(player(pin, n, finished) for n in range(1, PLAYERS + 1)))
    final = await asyncio.wait_for(host_task, 10)
    print(f"Oyunçu: {len(finished)}/{PLAYERS}, sual: {final['total']}, müddət: {time.perf_counter() - began:.1f} san")
    print(f"Cavab təsdiqi: orta {statistics.mean(lags) * 1000:.1f} ms, ən çox {max(lags) * 1000:.1f} ms, say {len(lags)}")
    print("Qalib:", final["standings"][0])
    for path in (f"/api/games/{final['game_id']}", f"/api/quizzes/{quiz_id}"):
        urllib.request.urlopen(urllib.request.Request(BASE + path, method="DELETE"))
    print("Sınaq oyunu və viktorinası silindi.")


sys.stdout.reconfigure(encoding="utf-8")
asyncio.run(main())
