"""Canlı oyunun məntiqi. Şəbəkədən və taymerlərdən asılı deyil, ona görə birbaşa test olunur."""
import random
import secrets
import time
from collections import Counter
from dataclasses import dataclass, field

from .questions import (UNSCORED, answer_label, answer_text, fold, grade, media_of, speed_points,
                        streak_bonus, valid_answer)

MAX_PLAYERS = 30
TEAM_NAMES = ("Do", "Re", "Mi", "Fa")
INTRO_SECONDS = 3
IMAGE_SECONDS = 6
GRACE_MS = 400
MAX_ADJUSTMENT = 100_000


class GameError(Exception):
    pass


def clean_name(name):
    name = " ".join(str(name or "").split())[:20]
    if not fold(name):
        raise GameError("Ad yazın")
    return name


@dataclass
class Answer:
    value: object
    elapsed_ms: int
    share: float
    correct: bool
    points: int = 0
    bonus: int = 0


@dataclass
class Player:
    name: str
    token: str
    team: int | None = None
    score: int = 0
    streak: int = 0
    best_streak: int = 0
    connected: bool = False
    answers: dict = field(default_factory=dict)
    pid: str | None = None

    @property
    def key(self):
        """Reytinqdə oyunçunun açarı: telefonun daimi ID-si, köhnə müştərilərdə ad."""
        return self.pid or fold(self.name)


class Game:
    def __init__(self, quiz, pin, shuffle=random.shuffle):
        self.quiz_id = quiz.get("id")
        self.title = quiz["title"]
        self.questions = quiz["questions"]
        self.pin = pin
        self.phase = "lobby"
        self.index = -1
        self.mode = "solo"
        self.team_count = 2
        self.auto = False
        self.players: dict[str, Player] = {}
        self.banned: set[str] = set()
        self.started_at = None
        self.opened_at = 0.0
        self.deadline = 0.0
        self.order_maps = {}
        self.closed = set()
        self.adjustments: list[dict] = []
        self._shuffle = shuffle

    # --- oyunçular -----------------------------------------------------
    def join(self, name, token=None, pid=None):
        """Eyni telefon (pid) yenidən qoşulanda köhnə oyunçu qaytarılır, xalı itmir."""
        if token and token in self.players:
            return self.players[token]
        if pid:
            if pid in self.banned:
                raise GameError("Aparıcı səni oyundan çıxarıb")
            known = next((p for p in self.players.values() if p.pid == pid), None)
            if known:
                return known
        name = clean_name(name)
        if "name:" + fold(name) in self.banned:
            raise GameError("Aparıcı bu adı oyundan çıxarıb")
        self._check_name_free(name)
        if len(self.players) >= MAX_PLAYERS:
            raise GameError("Otaq doludur")
        player = Player(name=name, token=secrets.token_urlsafe(16), pid=pid)
        if self.mode == "team" and self.phase != "lobby":
            player.team = self._smallest_team()
        self.players[player.token] = player
        return player

    def _check_name_free(self, name, owner=None):
        if any(p.token != owner and fold(p.name) == fold(name) for p in self.players.values()):
            raise GameError("Bu ad artıq götürülüb, başqa ad yazın")

    def rename(self, token, name):
        """Ad yalnız oyun başlamazdan əvvəl dəyişir ki, səhnədəki sıralama qarışmasın."""
        player = self.players.get(token)
        if player is None or self.phase != "lobby":
            raise GameError("Adı yalnız oyun başlamazdan əvvəl dəyişmək olar")
        name = clean_name(name)
        self._check_name_free(name, owner=token)
        player.name = name
        return name

    def kick(self, token):
        player = self.players.pop(token, None)
        if player:
            self.banned.add("name:" + fold(player.name))
            if player.pid:
                self.banned.add(player.pid)
        return player

    def _smallest_team(self):
        sizes = Counter(p.team for p in self.players.values() if p.team is not None)
        return min(range(self.team_count), key=lambda t: sizes[t])

    def configure(self, mode=None, team_count=None, auto=None):
        if mode in ("solo", "team") and self.phase == "lobby":
            self.mode = mode
        if team_count in (2, 3, 4) and self.phase == "lobby":
            self.team_count = team_count
        if isinstance(auto, bool):
            self.auto = auto

    def _assign_teams(self):
        roster = list(self.players.values())
        self._shuffle(roster)
        for position, player in enumerate(roster):
            player.team = position % self.team_count

    # --- gediş ---------------------------------------------------------
    @property
    def question(self):
        return self.questions[self.index] if 0 <= self.index < len(self.questions) else None

    def start(self):
        if self.phase != "lobby":
            raise GameError("Oyun artıq başlayıb")
        if not self.players:
            raise GameError("Hələ heç kim qoşulmayıb")
        if self.mode == "team":
            self._assign_teams()
        self.started_at = time.time()
        self._to_intro(0)

    def _to_intro(self, index):
        """Sualın şəkli və ya videosu varsa, əvvəlcə yalnız o göstərilir."""
        self.index = index
        self.phase = "media" if media_of(self.questions[index]) else "intro"

    def media_done(self):
        if self.phase != "media":
            return False
        self.phase = "intro"
        return True

    def open_question(self, now):
        if self.phase != "intro":
            return
        question = self.question
        if question["type"] == "order":
            mapping = list(range(len(question["options"])))
            while mapping == sorted(mapping):
                self._shuffle(mapping)
            self.order_maps[self.index] = mapping
        self.phase = "question"
        self.opened_at = now
        self.deadline = now + question["time"]

    def submit(self, token, value, now):
        """Cavabı qəbul edir. Xal yalnız sual bağlananda yazılır ki, vaxtından əvvəl görünməsin."""
        player = self.players.get(token)
        question = self.question
        if (self.phase != "question" or player is None or self.index in player.answers
                or now > self.deadline + GRACE_MS / 1000 or not valid_answer(question, value)):
            return False
        elapsed = int((now - self.opened_at) * 1000)
        share, correct = grade(question, value, self.order_maps.get(self.index))
        player.answers[self.index] = Answer(value, elapsed, share, correct)
        return True

    def ranks(self):
        names = {row["name"]: row["rank"] for row in self.standings()}
        return {p.token: names[p.name] for p in self.players.values()}

    def quip_context(self, index, previous_ranks):
        """Sual bağlanandan sonra hər oyunçunun vəziyyəti. Tokenlər AI-a getmir, yalnız sıra nömrəsi."""
        question = self.questions[index]
        ranks = self.ranks()
        tokens, players = [], []
        for number, player in enumerate(self.players.values(), start=1):
            answer = player.answers.get(index)
            tokens.append(player.token)
            players.append({
                "player": number, "name": player.name, "answered": answer is not None,
                "correct": bool(answer and answer.correct), "partly_correct": bool(answer and 0 < answer.share < 1),
                "answer": answer_text(question, answer.value, self.order_maps.get(index)) if answer else None,
                "seconds": round(answer.elapsed_ms / 1000, 1) if answer else None,
                "points_won": (answer.points + answer.bonus) if answer else 0,
                "streak": player.streak, "rank": ranks[player.token],
                "previous_rank": previous_ranks.get(player.token), "total_score": player.score})
        context = {"question": question["text"], "question_number": index + 1, "of": len(self.questions),
                   "kind": "poll (no right answer)" if question["type"] in UNSCORED else question["type"],
                   "correct_answer": answer_label(question) or None, "seconds_allowed": question["time"],
                   "players": players}
        return tokens, context

    def finale_context(self):
        result = self.export()
        rows = {p["name"]: p for p in result["players"]}
        tokens, players = [], []
        for number, player in enumerate(self.players.values(), start=1):
            row = rows[player.name]
            tokens.append(player.token)
            players.append({"player": number, "name": player.name, "rank": row["rank"], "score": row["score"],
                            "correct": row["correct"], "of": row["scored_total"], "best_streak": row["best_streak"],
                            "average_seconds": round(row["total_ms"] / row["answered"] / 1000, 1) if row["answered"] else None,
                            "team": row["team"]})
        return tokens, {"quiz": self.title, "players_count": len(players), "players": players}

    def explain_context(self, token, index):
        """AI izahı üçün sualın və oyunçunun cavabının konteksti. Cavabı açılmamış sual soruşula bilməz."""
        if not isinstance(index, int) or index not in self.closed:
            raise GameError("Bu sualın cavabı hələ açılmayıb")
        question = self.questions[index]
        if question["type"] in UNSCORED:
            raise GameError("Bu sualın düzgün cavabı yoxdur")
        player = self.players.get(token)
        answer = player.answers.get(index) if player else None
        return {"question": question, "correct_answer": answer_label(question),
                "player_answer": answer_text(question, answer.value, self.order_maps.get(index)) if answer else None,
                "player_correct": bool(answer and answer.correct)}

    def adjust(self, token, delta, reason=""):
        """Aparıcının əl ilə xal düzəlişi (ədalətsizlik olanda). Xal 0-dan aşağı düşmür, hər düzəliş qeyd olunur."""
        if self.phase == "lobby":
            raise GameError("Oyun hələ başlamayıb")
        player = self.players.get(token)
        if player is None:
            raise GameError("Oyunçu tapılmadı")
        if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0 or abs(delta) > MAX_ADJUSTMENT:
            raise GameError("Düzəliş miqdarı düzgün deyil")
        before = player.score
        player.score = max(0, before + delta)
        if player.score == before:
            raise GameError(f"{player.name} adlı oyunçunun xalı artıq 0-dır")
        entry = {"name": player.name, "key": player.key, "delta": player.score - before,
                 "reason": " ".join(str(reason or "").split())[:100],
                 "question": self.index + 1 if self.index >= 0 else None, "at": time.time()}
        self.adjustments.append(entry)
        return entry

    def all_answered(self):
        online = [p for p in self.players.values() if p.connected]
        return bool(online) and all(self.index in p.answers for p in online)

    def close_question(self):
        if self.phase != "question":
            return
        question = self.question
        if question["type"] not in UNSCORED and question["points"]:
            for player in self.players.values():
                answer = player.answers.get(self.index)
                if answer and answer.correct:
                    player.streak += 1
                    player.best_streak = max(player.best_streak, player.streak)
                    answer.bonus = streak_bonus(player.streak)
                else:
                    player.streak = 0
                if answer:
                    answer.points = speed_points(question, answer.share, answer.elapsed_ms)
                    player.score += answer.points + answer.bonus
        self.closed.add(self.index)
        self.phase = "reveal"

    def advance(self):
        """Aparıcının “Növbəti” düyməsi."""
        if self.phase == "reveal":
            self.phase = "board"
        elif self.phase == "board":
            if self.index + 1 < len(self.questions):
                self._to_intro(self.index + 1)
            else:
                self.phase = "podium"

    def finish(self):
        self.close_question()
        self.phase = "podium"

    # --- sıralama ------------------------------------------------------
    def standings(self):
        ordered = sorted(self.players.values(), key=lambda p: (-p.score, p.name.casefold()))
        rows, rank, previous = [], 0, None
        for position, player in enumerate(ordered, start=1):
            if player.score != previous:
                rank, previous = position, player.score
            rows.append({"rank": rank, "name": player.name, "score": player.score,
                         "team": player.team, "streak": player.streak})
        return rows

    def team_standings(self):
        """Komanda xalı üzvlərin ortalamasıdır ki, say fərqi üstünlük verməsin."""
        if self.mode != "team":
            return []
        rows = []
        for team in range(self.team_count):
            members = [p for p in self.players.values() if p.team == team]
            if members:
                rows.append({"team": team, "name": TEAM_NAMES[team], "members": len(members),
                             "score": round(sum(p.score for p in members) / len(members))})
        return sorted(rows, key=lambda r: -r["score"])

    def rank_of(self, player):
        return next(r["rank"] for r in self.standings() if r["name"] == player.name)

    # --- ekran görüntüləri --------------------------------------------
    def _public_question(self, now):
        question = self.question
        if question is None:
            return None
        data = {"type": question["type"], "text": question["text"], "media": media_of(question),
                "time": question["time"], "points": question["points"]}
        if self.phase in ("media", "intro"):
            return data
        if question["type"] == "order":
            mapping = self.order_maps.get(self.index, list(range(len(question["options"]))))
            data["options"] = [question["options"][i] for i in mapping]
        elif "options" in question:
            data["options"] = question["options"]
        if question["type"] == "slider":
            data.update(min=question["min"], max=question["max"], step=question["step"])
        if self.phase == "question":
            data["remaining_ms"] = max(0, int((self.deadline - now) * 1000))
        return data

    def _reveal(self):
        question = self.question
        data = {"answer": answer_label(question), "explanation": question["explanation"],
                "correct": question.get("correct", [])}
        answers = [p.answers[self.index] for p in self.players.values() if self.index in p.answers]
        data["answered"] = len(answers)
        data["right"] = sum(1 for a in answers if a.correct)
        kind = question["type"]
        if kind in ("choice", "truefalse", "poll", "multi"):
            counts = Counter()
            for answer in answers:
                counts.update(answer.value if kind == "multi" else [answer.value])
            data["counts"] = [counts[i] for i in range(len(question["options"]))]
        elif kind in ("text", "cloud"):
            labels = {}
            counts = Counter()
            for answer in answers:
                key = fold(answer.value)
                labels.setdefault(key, str(answer.value).strip())
                counts[key] += 1
            data["words"] = [{"text": labels[k], "count": c} for k, c in counts.most_common(30)]
        elif kind == "slider":
            values = [float(a.value) for a in answers]
            data["values"] = values
            data["average"] = round(sum(values) / len(values), 2) if values else None
        return data

    def _common(self, now):
        data = {"phase": self.phase, "pin": self.pin, "title": self.title, "mode": self.mode,
                "index": self.index, "total": len(self.questions)}
        if self.phase in ("media", "intro", "question", "reveal"):
            data["question"] = self._public_question(now)
        if self.phase == "reveal":
            data["reveal"] = self._reveal()
        return data

    def host_view(self, now):
        data = self._common(now)
        data.update(team_count=self.team_count, auto=self.auto, intro_seconds=INTRO_SECONDS,
                    image_seconds=IMAGE_SECONDS,
                    team_names=TEAM_NAMES[:self.team_count],
                    players=[{"name": p.name, "token": p.token, "team": p.team, "online": p.connected,
                              "score": p.score}
                             for p in self.players.values()])
        if self.phase == "question":
            data["answered"] = sum(1 for p in self.players.values() if self.index in p.answers)
        if self.phase in ("board", "podium"):
            data["standings"] = self.standings()
            data["teams"] = self.team_standings()
        return data

    def player_view(self, player, now):
        data = self._common(now)
        data["me"] = {"name": player.name, "token": player.token, "score": player.score,
                      "rank": self.rank_of(player), "streak": player.streak,
                      "players": len(self.players),
                      "team": TEAM_NAMES[player.team] if player.team is not None else None}
        answer = player.answers.get(self.index)
        if self.phase == "question":
            data["answered"] = answer is not None
        if self.phase == "reveal":
            data["result"] = {"answered": answer is not None,
                              "scored": self.question["type"] not in UNSCORED,
                              "correct": bool(answer and answer.correct),
                              "partial": bool(answer and 0 < answer.share < 1),
                              "points": answer.points if answer else 0,
                              "bonus": answer.bonus if answer else 0}
        if self.phase == "lobby":
            data["roster"] = [p.name for p in self.players.values()]
        if self.phase == "board":
            data["standings"] = [{k: row[k] for k in ("rank", "name", "score")} for row in self.standings()[:5]]
            data["teams"] = self.team_standings()
        if self.phase == "podium":
            data["top"] = self.standings()[:3]
            data["teams"] = self.team_standings()
            data["review"] = [
                {"index": i, "text": self.questions[i]["text"], "answer": answer_label(self.questions[i]),
                 "correct": bool(player.answers.get(i) and player.answers[i].correct)}
                for i in sorted(self.closed) if self.questions[i]["type"] not in UNSCORED]
        return data

    # --- yadda saxlamaq ------------------------------------------------
    def export(self):
        """Oyun bitəndə bazaya yazılacaq nəticə."""
        ranks = {row["name"]: row["rank"] for row in self.standings()}
        scored = [i for i in sorted(self.closed)
                  if self.questions[i]["type"] not in UNSCORED and self.questions[i]["points"]]
        players = []
        for player in self.players.values():
            answers = [player.answers[i] for i in scored if i in player.answers]
            right = sum(1 for a in answers if a.correct)
            players.append({
                "key": player.key, "name": player.name, "score": player.score,
                "team": TEAM_NAMES[player.team] if player.team is not None else None,
                "rank": ranks[player.name], "correct": right, "answered": len(answers),
                "scored_total": len(scored), "best_streak": player.best_streak,
                "total_ms": sum(a.elapsed_ms for a in answers),
                "perfect": len(scored) >= 5 and right == len(scored),
            })
        rows = [{"index": i, "key": p.key, "value": a.value, "correct": a.correct,
                 "points": a.points + a.bonus, "elapsed_ms": a.elapsed_ms}
                for p in self.players.values() for i, a in p.answers.items()]
        return {"quiz_id": self.quiz_id, "title": self.title, "pin": self.pin, "mode": self.mode,
                "questions": self.questions, "closed": sorted(self.closed),
                "started_at": self.started_at, "ended_at": time.time(),
                "players": players, "answers": rows, "teams": self.team_standings(),
                "adjustments": self.adjustments}
