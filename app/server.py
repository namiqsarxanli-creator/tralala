"""HTTP API və canlı otaqlar (WebSocket)."""
import asyncio
import csv
import io
import json
import logging
import os
import random
import re
import secrets
import socket
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

import segno
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ai, db, library
from .game import IMAGE_SECONDS, INTRO_SECONDS, Game, GameError, Player
from .tournament import MATCH_LENGTHS, Tournament
from .questions import QuestionError, answer_label, clean_question, media_of

log = logging.getLogger("tralala")
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
UPLOADS = db.DATA_DIR / "uploads"
PORT = int(os.getenv("TRALALA_PORT", "8020"))
PID_PATTERN = re.compile(r"[0-9a-f]{32}")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
REVEAL_AUTO_SECONDS = 6
BOARD_AUTO_SECONDS = 5
MAX_QUESTIONS_TO_AI = 20
AI_JOKE_TIMEOUT = 25
RESULT_SECONDS = 8
MAX_SUDDEN_DEATH = 3
ROOM_IDLE_SECONDS = 3 * 3600
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024  # hər telefon videonu ayrıca yükləyir
UPLOAD_CHUNK = 1024 * 1024


def sniff(head):
    """Faylın növünü adına görə yox, məzmununa görə müəyyən edir."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"GIF8"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:8] == b"ftyp" and head[8:12] != b"qt  ":
        return "mp4"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "webm"
    return None


def lan_ip():
    """Telefonların qoşulacağı ünvan. UDP “connect” heç nə göndərmir, sadəcə əsas şəbəkəni seçir."""
    configured = os.getenv("TRALALA_LAN_IP")
    if configured:
        return configured
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def same_origin(headers):
    origin = headers.get("origin")
    return not origin or urlsplit(origin).netloc == headers.get("host")


def is_local(connection):
    return (connection.client is not None and connection.client.host in LOOPBACK
            and same_origin(connection.headers))


def require_local(request: Request):
    """İdarəetmə yalnız serverin işlədiyi kompüterdən mümkündür, oyunçular ora girə bilmir."""
    if not is_local(request):
        raise HTTPException(403, "Bu bölmə yalnız aparıcının kompüterindən açılır")


class Conn:
    """Bir bağlantı. Görüntü tam vəziyyət olduğu üçün yavaş telefona yalnız ən sonuncusu gedir."""

    def __init__(self, ws):
        self.ws = ws
        self.latest = None
        self.events = []
        self.ready = asyncio.Event()
        self.task = asyncio.create_task(self._writer())

    def push(self, data):
        self.latest = data
        self.ready.set()

    def event(self, data):
        """Vəziyyət yeniləməsi kimi əvəzlənməyən mesaj: hamısı sırası ilə çatdırılır."""
        self.events.append(data)
        self.ready.set()

    async def _writer(self):
        with suppress(Exception):
            while True:
                await self.ready.wait()
                self.ready.clear()
                while self.events:
                    await self.ws.send_text(json.dumps(self.events.pop(0), ensure_ascii=False))
                if self.latest is not None:
                    latest, self.latest = self.latest, None
                    await self.ws.send_text(json.dumps(latest, ensure_ascii=False))

    async def flush_and_close(self, data):
        self.task.cancel()
        with suppress(Exception):
            await self.ws.send_text(json.dumps(data, ensure_ascii=False))
            await self.ws.close()


class Room:
    def __init__(self, game):
        self.game = game
        self.hosts: set[Conn] = set()
        self.players: dict[str, Conn] = {}
        self.timer = None
        self.saved_game_id = None
        self.touched = time.time()
        self.asks: dict[str, int] = {}
        self.asking: set[str] = set()
        self.jokes = True

    @property
    def phase(self):
        return self.game.phase

    @property
    def title(self):
        return self.game.title

    def join(self, name, token, pid=None):
        return self.game.join(name, token, pid).token

    def rename(self, token, name):
        self.game.rename(token, name)
        self.sync()

    async def ask(self, token, conn, payload):
        """Oyunçunun “niyə belədir?” sualı. AI cavabı gələnə qədər oyun dayanmır."""
        index = payload.get("index") if isinstance(payload, dict) else None
        message = payload.get("text") if isinstance(payload, dict) else None
        reply = {"ai": {"index": index, "question": " ".join(str(message or "").split())[:ai.MAX_MESSAGE_CHARS]}}
        try:
            if token in self.asking:
                raise ai.AIError("Əvvəlki sualının cavabı hələ yazılır")
            if self.asks.get(token, 0) >= MAX_QUESTIONS_TO_AI:
                raise ai.AIError(f"Bu oyunda ən çox {MAX_QUESTIONS_TO_AI} sual soruşmaq olar")
            if not self.game:
                raise ai.AIError("Bu duel artıq bitib")
            try:
                context = self.game.explain_context(token, index)
            except GameError as error:
                raise ai.AIError(str(error)) from error
            self.asking.add(token)
            self.asks[token] = self.asks.get(token, 0) + 1
            reply["ai"]["answer"] = await ai.explain(message=message, **context)
        except ai.AIError as error:
            reply["ai"]["error"] = str(error)
        except Exception:
            log.exception("AI izahı alınmadı")
            reply["ai"]["error"] = "AI cavab verə bilmədi. Yenidən soruş."
        finally:
            self.asking.discard(token)
        conn.event(reply)

    def set_online(self, token, online):
        player = self.game.players.get(token)
        if player:
            player.connected = online

    def submit(self, token, answer):
        return self.game.submit(token, answer, time.monotonic())

    def sync(self, only=None):
        """Hər kəsə öz görüntüsünü göndərir. `only` verilsə, aparıcı və həmin oyunçu."""
        now = time.monotonic()
        self.touched = time.time()
        game = self.game
        host_view = game.host_view(now)
        host_view["join_url"] = join_url(game.pin)
        host_view["game_id"] = self.saved_game_id
        host_view.update(jokes=self.jokes, ai_ready=ai.configured())
        for conn in self.hosts:
            conn.push(host_view)
        for token, conn in self.players.items():
            if only is None or token == only:
                player = game.players.get(token)
                if player:
                    conn.push(game.player_view(player, now))

    def _after(self, seconds, action):
        self.cancel_timer()

        async def run():
            await asyncio.sleep(seconds)
            self.timer = None
            await action()

        self.timer = asyncio.create_task(run())

    def cancel_timer(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def begin_round(self):
        """Media varsa: şəkil bir neçə saniyə görünür, video isə səhnədə bitənə qədər oynayır."""
        self.sync()
        if self.game.phase == "media":
            if media_of(self.game.question)["kind"] == "image":
                self._after(IMAGE_SECONDS, self.end_media)
            else:
                self.cancel_timer()
        else:
            self._after(INTRO_SECONDS, self.open_question)

    async def end_media(self):
        if self.game.media_done():
            self.begin_round()

    async def open_question(self):
        self.game.open_question(time.monotonic())
        self.sync()
        self._after(self.game.question["time"] + 0.5, self.close_question)

    async def close_question(self):
        self.cancel_timer()
        was_open = self.game.phase == "question"
        previous = self.game.ranks() if was_open else {}
        self.game.close_question()
        self.sync()
        if was_open:
            self.launch_quips(self.game.index, previous)
        if self.game.auto:
            self._after(REVEAL_AUTO_SECONDS, self.next_step)

    async def next_step(self):
        self.cancel_timer()
        game = self.game
        game.advance()
        if game.phase in ("media", "intro"):
            self.begin_round()
        elif game.phase == "podium":
            await self.save()
            self.sync()
            self.launch_finale()
        else:
            self.sync()
            if game.auto:
                self._after(BOARD_AUTO_SECONDS, self.next_step)

    async def finish(self):
        self.cancel_timer()
        if self.game.phase == "podium":
            return
        was_open = self.game.phase == "question"
        previous = self.game.ranks() if was_open else {}
        self.game.finish()
        await self.save()
        self.sync()
        if was_open:
            self.launch_quips(self.game.index, previous)
        self.launch_finale()

    async def save(self):
        if self.saved_game_id is None and self.game.closed and self.game.players:
            self.saved_game_id = await asyncio.to_thread(db.save_game, self.game.export())

    async def maybe_close_early(self):
        if self.game and self.game.phase == "question" and self.game.all_answered():
            await self.close_question()

    async def host_action(self, message):
        action = message.get("action")
        game = self.game
        if action == "config":
            game.configure(message.get("mode"), message.get("team_count"), message.get("auto"))
            if isinstance(message.get("jokes"), bool):
                self.jokes = message["jokes"]
            self.sync()
            if game.auto and game.phase in ("reveal", "board") and self.timer is None:
                self._after(REVEAL_AUTO_SECONDS, self.next_step)
        elif action == "start":
            game.start()
            self.begin_round()
        elif action == "media_done":
            await self.end_media()
        elif action == "next":
            if game.phase == "media":
                await self.end_media()
            elif game.phase == "question":
                await self.close_question()
            elif game.phase in ("reveal", "board"):
                await self.next_step()
        elif action == "kick":
            token = message.get("token")
            if game.kick(token):
                conn = self.players.pop(token, None)
                if conn:
                    await conn.flush_and_close({"phase": "kicked"})
                self.sync()
                await self.maybe_close_early()
        elif action == "finish":
            await self.finish()
        elif action == "adjust":
            await self.adjust(message)

    # --- AI zarafatları --------------------------------------------------
    def jokes_on(self):
        return self.jokes and ai.configured() and bool(self.players)

    def launch_quips(self, index, previous):
        """Konteksti indi götürür (oyun irəli getsə də dəyişməsin), AI-a fonda göndərir."""
        if self.jokes_on():
            tokens, context = self.game.quip_context(index, previous)
            asyncio.create_task(self._deliver(ai.quips, tokens, context, lambda line: {"quip": {"index": index, **line}}))

    def launch_finale(self):
        if self.jokes_on() and self.game.closed:
            tokens, context = self.game.finale_context()
            asyncio.create_task(self._deliver(ai.finale, tokens, context, lambda line: {"finale": line}))

    async def _deliver(self, make, tokens, context, wrap):
        try:
            lines = await asyncio.wait_for(make(context), timeout=AI_JOKE_TIMEOUT)
        except Exception:  # zarafat gəlməsə oyun davam edir, sadəcə şərh olmur
            log.exception("AI zarafatı alınmadı")
            return
        for number, line in lines.items():
            conn = self.players.get(tokens[number - 1])
            if conn:
                conn.event(wrap(line))

    async def adjust(self, message):
        """Aparıcı oyunçunun xalını silir və ya qaytarır. Oyunçuya telefonda bildiriş gedir."""
        token = message.get("token")
        player = self.game.players.get(token) if self.game else None
        if player is None:
            raise GameError("Oyunçu tapılmadı")
        delta = -player.score if message.get("zero") else message.get("delta")
        entry = self.game.adjust(token, delta, message.get("reason"))
        conn = self.players.get(token)
        if conn:
            text = f"Aparıcı xalını dəyişdi: {entry['delta']:+d}"
            conn.event({"toast": text + (f" ({entry['reason']})" if entry["reason"] else ""), "bad": entry["delta"] < 0})
        if self.saved_game_id is not None:
            # Oyun artıq bitib və yazılıb: nəticə yeni xallarla yenidən yazılır ki, reytinq də düzəlsin.
            self.saved_game_id = await asyncio.to_thread(db.save_game, self.game.export(), self.saved_game_id)
        self.sync()

    async def close(self):
        self.cancel_timer()
        for conn in [*self.hosts, *self.players.values()]:
            await conn.flush_and_close({"phase": "closed"})


class TournamentRoom(Room):
    """Turnir otağı: bağlantılar bütün turnir boyu qalır, hər duel ayrıca kiçik `Game` olur."""

    def __init__(self, tournament, pin, tournament_id):
        super().__init__(None)
        self.t = tournament
        self.pin = pin
        self.tournament_id = tournament_id
        self.tokens: dict[str, str] = {}
        self.online: set[str] = set()
        self.auto = True
        self.sudden = 0

    @property
    def phase(self):
        return self.t.phase

    @property
    def title(self):
        return self.t.title

    def token_of(self, name):
        return next((token for token, entrant in self.tokens.items() if entrant == name), None)

    def join(self, name, token, pid=None):
        if token and token in self.tokens:
            return token
        entrant = self.t.add(name, pid)
        known = self.token_of(entrant)
        if known:
            same_phone = pid is not None and self.t.ids.get(entrant) == pid
            if known in self.online and not same_phone:
                raise GameError("Bu adla artıq kimsə turnirdədir")
            return known
        token = secrets.token_urlsafe(16)
        self.tokens[token] = entrant
        return token

    def rename(self, token, name):
        old = self.tokens[token]
        self.tokens[token] = self.t.rename(old, name)
        self.sync()

    def set_online(self, token, online):
        (self.online.add if online else self.online.discard)(token)
        if self.game and token in self.game.players:
            self.game.players[token].connected = online

    def submit(self, token, answer):
        return bool(self.game) and self.game.submit(token, answer, time.monotonic())

    # --- görüntülər ----------------------------------------------------
    def duel(self):
        if not self.game or not self.t.current:
            return None
        r, m = self.t.current
        match = self.t.rounds[r][m]
        scores = {p.name: p.score for p in self.game.players.values()}
        return {"a": match["a"], "b": match["b"], "score": [scores.get(match["a"], 0), scores.get(match["b"], 0)],
                "round": self.t.round_label(r), "sudden": self.sudden}

    def host_view(self, now):
        t = self.t
        nxt = t.next_match()
        data = {"kind": "tournament", "phase": t.phase, "pin": self.pin, "title": t.title,
                "join_url": join_url(self.pin), "per_match": t.per_match, "lengths": MATCH_LENGTHS,
                "pool": len(t.pool), "auto": self.auto, "id": self.tournament_id,
                "jokes": self.jokes, "ai_ready": ai.configured(),
                "entrants": [{"name": n, "online": self.token_of(n) in self.online} for n in t.entrants],
                "bracket": t.bracket(), "next": nxt, "result": t.result, "champion": t.champion,
                "next_round": t.round_label(nxt[0]) if nxt else None}
        if t.phase == "match" and self.game:
            match = self.game.host_view(now)
            match.update(join_url=data["join_url"], game_id=None)
            data["match"] = match
            data["duel"] = self.duel()
        return data

    def player_view(self, token, now):
        t = self.t
        name = self.tokens[token]
        if t.phase == "match" and self.game and token in self.game.players:
            data = self.game.player_view(self.game.players[token], now)
            data.update(kind="tournament", duel=self.duel())
            return data
        return {"kind": "tournament", "phase": "t_" + t.phase, "title": t.title, "pin": self.pin,
                "me": {"name": name, "token": token, "score": "Turnir"},
                "entrants": len(t.entrants), "out": t.eliminated(name), "opponent": t.opponent(name),
                "champion": t.champion, "duel": self.duel(), "result": t.result,
                "drawn": bool(t.rounds), "bracket": t.bracket(),
                # İzləyici gedən duelin sualını və cavabını telefonda görür.
                "watch": self.game._common(now) if self.game else None}

    def sync(self, only=None):
        now = time.monotonic()
        self.touched = time.time()
        host_view = self.host_view(now)
        for conn in self.hosts:
            conn.push(host_view)
        for token, conn in self.players.items():
            if (only is None or token == only) and token in self.tokens:
                conn.push(self.player_view(token, now))

    async def persist(self):
        await asyncio.to_thread(db.save_tournament, self.tournament_id, self.t.to_dict(), self.t.champion)

    # --- duel ----------------------------------------------------------
    async def start_match(self):
        spot = self.t.next_match()
        if not spot:
            raise GameError("Oynanacaq matç qalmayıb")
        r, m = spot
        match = self.t.rounds[r][m]
        game = Game({"id": self.t.quiz_id, "title": f"{match['a']} – {match['b']}",
                     "questions": self.t.take_questions(self.t.per_match)}, self.pin)
        game.auto = self.auto
        for name in (match["a"], match["b"]):
            token = self.token_of(name)
            if token is None:
                token = secrets.token_urlsafe(16)
                self.tokens[token] = name
            game.players[token] = Player(name=name, token=token, connected=token in self.online)
        self.game, self.sudden = game, 0
        self.t.phase, self.t.current, self.t.result = "match", [r, m], None
        game.start()
        self.begin_round()

    async def next_step(self):
        """Duelin son sualından sonra: bərabərlikdə əlavə sual, yoxsa nəticə."""
        game = self.game
        if game and game.phase == "board" and game.index + 1 >= len(game.questions):
            a, b = self.duel()["score"]
            if a == b and self.sudden < MAX_SUDDEN_DEATH:
                self.sudden += 1
                game.questions.append(self.t.take_questions(1)[0])
            else:
                await self.end_match()
                return
        await super().next_step()

    def _decide(self):
        game = self.game
        r, m = self.t.current
        match = self.t.rounds[r][m]
        players = {p.name: p for p in game.players.values()}
        a, b = players[match["a"]], players[match["b"]]
        if a.score != b.score:
            return (a if a.score > b.score else b), ""
        right = {p.name: sum(1 for x in p.answers.values() if x.correct) for p in (a, b)}
        if right[a.name] != right[b.name]:
            return max((a, b), key=lambda p: right[p.name]), "Bərabərlik: daha çox düz cavab"
        speed = {p.name: sum(x.elapsed_ms for x in p.answers.values() if x.correct) for p in (a, b)}
        if right[a.name] and speed[a.name] != speed[b.name]:
            return min((a, b), key=lambda p: speed[p.name]), "Bərabərlik: daha sürətli cavab"
        return random.choice((a, b)), "Bərabərlik: püşk"

    async def end_match(self, note=""):
        self.cancel_timer()
        self.game.close_question()
        winner, reason = self._decide()
        r, m = self.t.current
        match = self.t.rounds[r][m]
        score = self.duel()["score"]
        self.t.record(r, m, winner.name, score, note or reason)
        self._show_result(r, match, winner.name, score, note or reason)
        self.game = None
        await self.persist()
        self.sync()

    async def walkover(self, winner):
        spot = self.t.next_match()
        if not spot:
            raise GameError("Oynanacaq matç qalmayıb")
        r, m = spot
        match = self.t.rounds[r][m]
        if winner not in (match["a"], match["b"]):
            raise GameError("Bu oyunçu növbəti matçda deyil")
        self.t.record(r, m, winner, [0, 0], "Texniki qələbə")
        self._show_result(r, match, winner, [0, 0], "Texniki qələbə")
        await self.persist()
        self.sync()

    def _show_result(self, r, match, winner, score, note):
        loser = match["b"] if winner == match["a"] else match["a"]
        self.t.result = {"a": match["a"], "b": match["b"], "winner": winner, "loser": loser, "score": score,
                         "note": note, "round": self.t.round_label(r), "final": self.t.champion is not None}
        self.t.phase, self.t.current = "result", None
        if self.auto:
            self._after(RESULT_SECONDS, self.after_result)

    async def after_result(self):
        if self.t.phase == "result":
            self.cancel_timer()
            self.t.phase = "champion" if self.t.champion else "bracket"
            await self.persist()
            self.sync()

    # --- aparıcının düymələri -------------------------------------------
    async def host_action(self, message):
        action = message.get("action")
        t = self.t
        if t.phase == "match":
            if action in ("next", "media_done", "adjust"):
                await super().host_action(message)
            elif action == "finish":
                await self.end_match("Aparıcı matçı vaxtından əvvəl bitirdi")
            return
        if action == "config":
            t.configure(message.get("per_match"))
            if isinstance(message.get("auto"), bool):
                self.auto = message["auto"]
            if isinstance(message.get("jokes"), bool):
                self.jokes = message["jokes"]
            self.sync()
        elif action == "kick" and t.phase == "lobby":
            name = message.get("name")
            if t.remove(name):
                token = self.token_of(name)
                if token:
                    del self.tokens[token]
                    self.online.discard(token)
                    conn = self.players.pop(token, None)
                    if conn:
                        await conn.flush_and_close({"phase": "kicked"})
                await self.persist()
                self.sync()
        elif action == "draw":
            t.draw()
            await self.persist()
            self.sync()
        elif action == "start_match" and t.phase == "bracket":
            await self.start_match()
        elif action == "walkover" and t.phase == "bracket":
            await self.walkover(message.get("winner"))
        elif action == "next" and t.phase == "result":
            await self.after_result()


rooms: dict[str, Room] = {}


def join_url(pin):
    return f"http://{lan_ip()}:{PORT}/?pin={pin}"


def new_pin():
    while True:
        pin = f"{secrets.randbelow(900000) + 100000}"
        if pin not in rooms:
            return pin


async def sweep_rooms():
    while True:
        await asyncio.sleep(600)
        limit = time.time() - ROOM_IDLE_SECONDS
        for pin, room in list(rooms.items()):
            if room.touched < limit:
                await room.close()
                rooms.pop(pin, None)


@asynccontextmanager
async def lifespan(_app):
    db.init()
    library.load()
    UPLOADS.mkdir(parents=True, exist_ok=True)
    sweeper = asyncio.create_task(sweep_rooms())
    yield
    sweeper.cancel()


app = FastAPI(title="Tralala", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
local = [Depends(require_local)]


# --- səhifələr ---------------------------------------------------------
@app.get("/")
def page_join():
    return FileResponse(STATIC / "index.html")


@app.get("/admin", dependencies=local)
def page_admin():
    return FileResponse(STATIC / "admin.html")


@app.get("/stage", dependencies=local)
def page_stage():
    return FileResponse(STATIC / "stage.html")


@app.get("/tournament", dependencies=local)
def page_tournament():
    return FileResponse(STATIC / "tournament.html")


@app.exception_handler(HTTPException)
async def http_error(_request, error):
    return JSONResponse({"error": error.detail}, status_code=error.status_code)


# --- viktorinalar ------------------------------------------------------
def _clean_quiz(body):
    title = str(body.get("title") or "").strip()[:80]
    if not title:
        raise HTTPException(400, "Viktorinanın adını yazın")
    raw = body.get("questions")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, "Ən azı bir sual əlavə edin")
    if len(raw) > 100:
        raise HTTPException(400, "Bir viktorinada ən çox 100 sual ola bilər")
    questions = []
    for number, item in enumerate(raw, start=1):
        try:
            questions.append(clean_question(item))
        except QuestionError as error:
            raise HTTPException(400, f"Sual {number}: {error}") from error
    return title, str(body.get("description") or "").strip()[:200], questions


@app.get("/api/quizzes", dependencies=local)
def quizzes_list():
    return db.list_quizzes()


@app.get("/api/quizzes/{quiz_id}", dependencies=local)
def quiz_get(quiz_id: int):
    quiz = db.get_quiz(quiz_id)
    if not quiz:
        raise HTTPException(404, "Viktorina tapılmadı")
    return quiz


@app.post("/api/quizzes", dependencies=local)
async def quiz_create(request: Request):
    title, description, questions = _clean_quiz(await request.json())
    return {"id": db.save_quiz(title, description, questions)}


@app.put("/api/quizzes/{quiz_id}", dependencies=local)
async def quiz_update(quiz_id: int, request: Request):
    title, description, questions = _clean_quiz(await request.json())
    if db.save_quiz(title, description, questions, quiz_id) is None:
        raise HTTPException(404, "Viktorina tapılmadı")
    return {"id": quiz_id}


@app.get("/api/quizzes/{quiz_id}/export", dependencies=local)
def quiz_export(quiz_id: int):
    quiz = db.get_quiz(quiz_id)
    if not quiz:
        raise HTTPException(404, "Viktorina tapılmadı")
    body = {"title": quiz["title"], "description": quiz["description"], "questions": quiz["questions"]}
    return Response(json.dumps(body, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="tralala-viktorina-{quiz_id}.json"'})


@app.post("/api/quizzes/import", dependencies=local)
async def quiz_import(file: UploadFile = File(...)):
    """Bir viktorina və ya viktorinalar siyahısı olan JSON faylı. Bütün suallar yoxlanır, səhv varsa heç nə yazılmır."""
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Fayl çox böyükdür")
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(400, "Fayl düzgün JSON deyil") from error
    items = payload if isinstance(payload, list) else [payload]
    if not items or not all(isinstance(item, dict) for item in items):
        raise HTTPException(400, "Faylda viktorina tapılmadı")
    cleaned = []
    for number, item in enumerate(items, start=1):
        try:
            cleaned.append(_clean_quiz(item))
        except HTTPException as error:
            prefix = f"{number}-ci viktorina, " if len(items) > 1 else ""
            raise HTTPException(400, prefix + error.detail) from error
    ids = [db.save_quiz(title, description, questions) for title, description, questions in cleaned]
    return {"ids": ids, "count": sum(len(q) for _, _, q in cleaned)}


@app.delete("/api/quizzes/{quiz_id}", dependencies=local)
def quiz_delete(quiz_id: int):
    if not db.delete_quiz(quiz_id):
        raise HTTPException(404, "Viktorina tapılmadı")
    return {"ok": True}


@app.post("/api/upload", dependencies=local)
async def upload_media(file: UploadFile = File(...)):
    head = await file.read(16)
    extension = sniff(head)
    if not extension:
        raise HTTPException(400, "Şəkil PNG, JPG, GIF, WEBP, video isə MP4 və ya WEBM olmalıdır")
    video = extension in ("mp4", "webm")
    limit = MAX_VIDEO_BYTES if video else MAX_IMAGE_BYTES
    name = f"{secrets.token_hex(16)}.{extension}"
    target = UPLOADS / name
    size = len(head)
    too_big = False
    with target.open("wb") as out:
        out.write(head)
        while chunk := await file.read(UPLOAD_CHUNK):
            size += len(chunk)
            if size > limit:
                too_big = True
                break
            out.write(chunk)
    if too_big:
        target.unlink(missing_ok=True)
        raise HTTPException(413, f"Fayl {limit // (1024 * 1024)} MB-dan böyük ola bilməz")
    return {"url": f"/uploads/{name}", "kind": "video" if video else "image"}


# --- otaqlar -----------------------------------------------------------
@app.post("/api/rooms", dependencies=local)
async def room_create(request: Request):
    body = await request.json()
    quiz = db.get_quiz(int(body.get("quiz_id", 0)))
    if not quiz:
        raise HTTPException(404, "Viktorina tapılmadı")
    pin = new_pin()
    rooms[pin] = Room(Game(quiz, pin))
    return {"pin": pin}


@app.get("/api/rooms/{pin}")
def room_status(pin: str):
    room = rooms.get(pin)
    if not room:
        raise HTTPException(404, "Bu kodla oyun tapılmadı")
    return {"pin": pin, "phase": room.phase, "title": room.title}


@app.get("/api/rooms/{pin}/qr.svg", dependencies=local)
def room_qr(pin: str):
    if pin not in rooms:
        raise HTTPException(404, "Oyun tapılmadı")
    buffer = io.BytesIO()
    segno.make(join_url(pin), error="m").save(buffer, kind="svg", scale=8, border=2,
                                              dark="#1F2A44", light="#FFFFFF")
    return Response(buffer.getvalue(), media_type="image/svg+xml")


# --- turnirlər ----------------------------------------------------------
def live_tournament_pin(tournament_id):
    return next((pin for pin, room in rooms.items()
                 if isinstance(room, TournamentRoom) and room.tournament_id == tournament_id), None)


def open_tournament_room(tournament_id, tournament):
    pin = live_tournament_pin(tournament_id)
    if pin is None:
        pin = new_pin()
        rooms[pin] = TournamentRoom(tournament, pin, tournament_id)
    return pin


@app.post("/api/tournaments", dependencies=local)
async def tournament_create(request: Request):
    body = await request.json()
    title = str(body.get("title") or "").strip()[:80]
    if not title:
        raise HTTPException(400, "Turnirin adını yazın")
    quiz = db.get_quiz(int(body.get("quiz_id") or 0))
    if not quiz:
        raise HTTPException(404, "Sual mənbəyi üçün viktorina seçin")
    per_match = int(body.get("per_match") or 5)
    if per_match not in MATCH_LENGTHS:
        raise HTTPException(400, "Duel sual sayı düzgün deyil")
    try:
        tournament = Tournament(title, quiz["questions"], per_match, quiz["id"])
    except GameError as error:
        raise HTTPException(400, str(error)) from error
    tournament_id = db.create_tournament(title, quiz["id"], tournament.to_dict())
    return {"id": tournament_id, "pin": open_tournament_room(tournament_id, tournament)}


@app.get("/api/tournaments", dependencies=local)
def tournament_list():
    return [{**t, "pin": live_tournament_pin(t["id"])} for t in db.list_tournaments()]


@app.get("/api/tournaments/{tournament_id}", dependencies=local)
def tournament_get(tournament_id: int):
    row = db.get_tournament(tournament_id)
    if not row:
        raise HTTPException(404, "Turnir tapılmadı")
    pin = live_tournament_pin(tournament_id)
    tournament = rooms[pin].t if pin else Tournament.from_dict(row["state"])
    return {"id": tournament_id, "title": tournament.title, "phase": tournament.phase, "pin": pin,
            "champion": tournament.champion, "entrants": tournament.entrants, "bracket": tournament.bracket()}


@app.post("/api/tournaments/{tournament_id}/open", dependencies=local)
def tournament_open(tournament_id: int):
    row = db.get_tournament(tournament_id)
    if not row:
        raise HTTPException(404, "Turnir tapılmadı")
    return {"pin": open_tournament_room(tournament_id, Tournament.from_dict(row["state"]))}


@app.delete("/api/tournaments/{tournament_id}", dependencies=local)
async def tournament_delete(tournament_id: int):
    pin = live_tournament_pin(tournament_id)
    if pin:
        await rooms.pop(pin).close()
    if not db.delete_tournament(tournament_id):
        raise HTTPException(404, "Turnir tapılmadı")
    return {"ok": True}


# --- hesabatlar və reytinq ---------------------------------------------
def game_report(game):
    closed = set(game["closed"])
    by_question = {}
    for answer in game["answers"]:
        by_question.setdefault(answer["q_index"], []).append(answer)
    questions = []
    for index, question in enumerate(game["questions"]):
        if index not in closed:
            continue
        answers = by_question.get(index, [])
        right = sum(a["correct"] for a in answers)
        questions.append({
            "index": index, "text": question["text"], "type": question["type"],
            "answer": answer_label(question), "answered": len(answers), "right": right,
            "accuracy": round(100 * right / game["player_count"]) if game["player_count"] else 0,
            "avg_ms": round(sum(a["elapsed_ms"] for a in answers) / len(answers)) if answers else 0,
        })
    return {key: game[key] for key in ("id", "title", "mode", "player_count", "started_at", "ended_at",
                                       "players", "teams", "adjustments")} | {"questions": questions}


@app.get("/api/games", dependencies=local)
def games_list():
    return db.list_games()


@app.get("/api/games/{game_id}", dependencies=local)
def game_detail(game_id: int):
    game = db.get_game(game_id)
    if not game:
        raise HTTPException(404, "Oyun tapılmadı")
    return game_report(game)


def csv_safe(value):
    """Excel-də ad formul kimi işləməsin deyə."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@app.get("/api/games/{game_id}/csv", dependencies=local)
def game_csv(game_id: int):
    game = db.get_game(game_id)
    if not game:
        raise HTTPException(404, "Oyun tapılmadı")
    report = game_report(game)
    questions = report["questions"]
    answers = {(a["player_key"], a["q_index"]): a for a in game["answers"]}
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    adjusted = {}
    for entry in game["adjustments"]:
        adjusted[entry["key"]] = adjusted.get(entry["key"], 0) + entry["delta"]
    writer.writerow(["Yer", "Ad", "Komanda", "Xal", "Aparıcı düzəlişi", "Düzgün", "Cavablanan",
                     *[f"S{q['index'] + 1}: {csv_safe(q['text'])}" for q in questions]])
    for player in game["players"]:
        cells = []
        for question in questions:
            answer = answers.get((player["player_key"], question["index"]))
            cells.append("-" if not answer else f"{'✓' if answer['correct'] else '✗'} {answer['points']}")
        writer.writerow([player["rank"], csv_safe(player["name"]), player["team"] or "", player["score"],
                         adjusted.get(player["player_key"], 0), player["correct"], player["answered"], *cells])
    return Response("﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="tralala-oyun-{game_id}.csv"'})


@app.delete("/api/games/{game_id}", dependencies=local)
def game_delete(game_id: int):
    if not db.delete_game(game_id):
        raise HTTPException(404, "Oyun tapılmadı")
    return {"ok": True}


@app.get("/api/leaderboard", dependencies=local)
def leaderboard():
    return {"all": db.leaderboard(), "week": db.leaderboard(db.week_start())}


# --- canlı bağlantılar -------------------------------------------------
async def _receive(ws):
    """Oxunmayan və ya obyekt olmayan mesajları nəzərə almır."""
    while True:
        try:
            message = json.loads(await ws.receive_text())
        except ValueError:
            continue
        if isinstance(message, dict):
            return message


@app.websocket("/ws/host/{pin}")
async def ws_host(ws: WebSocket, pin: str):
    if not is_local(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    room = rooms.get(pin)
    if not room:
        await ws.send_json({"phase": "closed"})
        await ws.close()
        return
    conn = Conn(ws)
    room.hosts.add(conn)
    room.sync()
    try:
        while True:
            message = await _receive(ws)
            try:
                await room.host_action(message)
            except GameError as error:
                conn.push({"error": str(error), "phase": room.phase, "keep": True})
    except WebSocketDisconnect:
        pass
    finally:
        room.hosts.discard(conn)
        conn.task.cancel()


@app.websocket("/ws/play/{pin}")
async def ws_play(ws: WebSocket, pin: str):
    await ws.accept()
    room = rooms.get(pin)
    if not room:
        await ws.send_json({"phase": "closed"})
        await ws.close()
        return
    try:
        hello = await asyncio.wait_for(_receive(ws), timeout=15)
        pid = hello.get("pid")
        pid = pid if isinstance(pid, str) and PID_PATTERN.fullmatch(pid) else None
        token = room.join(hello.get("name"), hello.get("token"), pid)
    except GameError as error:
        await ws.send_json({"phase": "refused", "error": str(error)})
        await ws.close()
        return
    except (asyncio.TimeoutError, WebSocketDisconnect):
        with suppress(Exception):
            await ws.close()
        return

    previous = room.players.get(token)
    if previous:
        await previous.flush_and_close({"phase": "replaced"})
    conn = Conn(ws)
    room.players[token] = conn
    room.set_online(token, True)
    room.sync()
    try:
        while True:
            message = await _receive(ws)
            if "answer" in message and room.submit(token, message["answer"]):
                room.sync(only=token)
                await room.maybe_close_early()
            elif "rename" in message:
                try:
                    room.rename(token, message["rename"])
                except GameError as error:
                    conn.event({"toast": str(error)})
            elif "ask" in message:
                # Ayrıca tapşırıq: AI cavabını gözləyərkən oyunçunun cavabları bloklanmasın.
                asyncio.create_task(room.ask(token, conn, message["ask"]))
    except WebSocketDisconnect:
        pass
    finally:
        conn.task.cancel()
        if room.players.get(token) is conn:
            del room.players[token]
            room.set_online(token, False)
            room.sync()
            await room.maybe_close_early()


app.mount("/uploads", StaticFiles(directory=UPLOADS, check_dir=False), name="uploads")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
