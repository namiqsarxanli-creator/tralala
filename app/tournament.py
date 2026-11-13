"""Pley-off turniri: iki nəfər qarşılaşır, qalib növbəti raunda keçir, uduzan çıxır.

Şəbəkədən asılı deyil. Duelin özü adi `Game` ilə oynanır, burada yalnız cədvəl saxlanılır.
"""
import random

from .game import GameError, clean_name
from .questions import UNSCORED, fold

MAX_ENTRANTS = 32
MATCH_LENGTHS = (1, 3, 5, 7)


def round_name(index, total):
    left = total - index
    return {1: "Final", 2: "Yarımfinal", 3: "Dörddəbir final"}.get(left, f"1/{2 ** (left - 1)} final")


def _match(a=None, b=None):
    return {"a": a, "b": b, "winner": None, "score": [0, 0], "note": ""}


class Tournament:
    def __init__(self, title, questions, per_match=5, quiz_id=None):
        pool = [q for q in questions if q["type"] not in UNSCORED and q["points"]]
        if not pool:
            raise GameError("Bu viktorinada xal gətirən sual yoxdur")
        self.title = title
        self.quiz_id = quiz_id
        self.pool = pool
        self.per_match = min(per_match, len(pool))
        self.entrants: list[str] = []
        self.ids: dict[str, str] = {}  # iştirakçının adı -> telefonun ID-si
        self.rounds: list[list[dict]] = []
        self.order = list(range(len(pool)))
        random.shuffle(self.order)
        self.cursor = 0
        self.phase = "lobby"
        self.current = None
        self.result = None

    # --- qeydiyyat -----------------------------------------------------
    def add(self, name, pid=None):
        """İştirakçını əlavə edir. Eyni telefon geri qayıdanda həmin iştirakçı qaytarılır.

        Başqa telefondan eyni adla gəlmək olmaz: belə hal başqasının yerinə oynamağa çevrilərdi."""
        if pid:
            known = next((entrant for entrant, owner in self.ids.items() if owner == pid), None)
            if known:
                return known
        name = clean_name(name)
        existing = next((e for e in self.entrants if fold(e) == fold(name)), None)
        if existing:
            owner = self.ids.get(existing)
            if owner and owner != pid:
                raise GameError("Bu ad başqa iştirakçıya məxsusdur" if self.phase == "lobby"
                                else "Bu iştirakçı başqa telefondan yazılıb")
            if pid:
                self.ids[existing] = pid
            return existing
        if self.phase != "lobby":
            raise GameError("Püşk artıq atılıb. Turnirə yalnız iştirakçılar qayıda bilər.")
        if len(self.entrants) >= MAX_ENTRANTS:
            raise GameError(f"Turnirdə ən çox {MAX_ENTRANTS} nəfər ola bilər")
        self.entrants.append(name)
        if pid:
            self.ids[name] = pid
        return name

    def rename(self, old, new):
        if self.phase != "lobby" or old not in self.entrants:
            raise GameError("Adı yalnız püşkdən əvvəl dəyişmək olar")
        new = clean_name(new)
        if any(fold(e) == fold(new) and e != old for e in self.entrants):
            raise GameError("Bu ad artıq götürülüb, başqa ad yazın")
        self.entrants[self.entrants.index(old)] = new
        if old in self.ids:
            self.ids[new] = self.ids.pop(old)
        return new

    def key_of(self, name):
        return self.ids.get(name) or fold(name)

    def remove(self, name):
        if self.phase == "lobby" and name in self.entrants:
            self.entrants.remove(name)
            self.ids.pop(name, None)
            return True
        return False

    def configure(self, per_match=None):
        if self.phase == "lobby" and per_match in MATCH_LENGTHS:
            self.per_match = min(per_match, len(self.pool))

    # --- püşk və cədvəl ------------------------------------------------
    def draw(self, shuffle=random.shuffle):
        if self.phase != "lobby":
            raise GameError("Püşk artıq atılıb")
        if len(self.entrants) < 2:
            raise GameError("Turnir üçün ən azı 2 iştirakçı lazımdır")
        names = list(self.entrants)
        shuffle(names)
        size = 1
        while size < len(names):
            size *= 2
        slots = names + [None] * (size - len(names))
        # Boş yerlər cütlərə bir-bir paylanır ki, heç vaxt boş-boşa matç yaranmasın.
        self.rounds = [[_match(slots[i], slots[size - 1 - i]) for i in range(size // 2)]]
        width = size // 4
        while width >= 1:
            self.rounds.append([_match() for _ in range(width)])
            width //= 2
        self._settle()
        self.phase = "bracket"

    def _settle(self):
        """Rəqibsiz qalanları irəli keçirir və qalibləri növbəti raunda yazır."""
        for r, matches in enumerate(self.rounds):
            for m, match in enumerate(matches):
                if r == 0 and match["winner"] is None and (match["a"] is None or match["b"] is None):
                    match["winner"] = match["a"] or match["b"]
                    match["note"] = "bye"
                if match["winner"] and r + 1 < len(self.rounds):
                    self.rounds[r + 1][m // 2]["a" if m % 2 == 0 else "b"] = match["winner"]

    @staticmethod
    def status(match):
        if match["note"] == "bye":
            return "bye"
        if match["winner"]:
            return "done"
        return "ready" if match["a"] and match["b"] else "waiting"

    def next_match(self):
        for r, matches in enumerate(self.rounds):
            for m, match in enumerate(matches):
                if self.status(match) == "ready":
                    return [r, m]
        return None

    def record(self, r, m, winner, score, note=""):
        match = self.rounds[r][m]
        if self.status(match) != "ready" or winner not in (match["a"], match["b"]):
            raise GameError("Bu matçın nəticəsi yazıla bilməz")
        match.update(winner=winner, score=list(score), note=note)
        self._settle()

    @property
    def champion(self):
        return self.rounds[-1][0]["winner"] if self.rounds else None

    def eliminated(self, name):
        return any(m["winner"] and m["winner"] != name and name in (m["a"], m["b"])
                   for matches in self.rounds for m in matches)

    def opponent(self, name):
        """Növbəti rəqib. None: rəqib hələ bəlli deyil və ya oyunçu artıq çıxıb."""
        for matches in self.rounds:
            for match in matches:
                if match["winner"] is None and name in (match["a"], match["b"]):
                    return match["b"] if match["a"] == name else match["a"]
        return None

    def take_questions(self, count):
        """Hər duelə hovuzdan növbəti suallar düşür ki, matçlar fərqli suallarla keçsin."""
        picked = []
        while len(picked) < min(count, len(self.pool)):
            if self.cursor >= len(self.order):
                random.shuffle(self.order)
                self.cursor = 0
            index = self.order[self.cursor]
            self.cursor += 1
            if index not in picked:
                picked.append(index)
        return [self.pool[i] for i in picked]

    def bracket(self):
        total = len(self.rounds)
        return [{"name": round_name(r, total),
                 "matches": [{**m, "status": self.status(m)} for m in matches]}
                for r, matches in enumerate(self.rounds)]

    def round_label(self, r):
        return round_name(r, len(self.rounds))

    # --- yadda saxlamaq ------------------------------------------------
    def to_dict(self):
        return {key: getattr(self, key) for key in
                ("title", "quiz_id", "pool", "per_match", "entrants", "ids", "rounds", "order", "cursor", "phase")}

    @classmethod
    def from_dict(cls, data):
        tournament = cls(data["title"], data["pool"], data["per_match"], data["quiz_id"])
        for key in ("entrants", "rounds", "order", "cursor"):
            setattr(tournament, key, data[key])
        tournament.ids = data.get("ids", {})
        # Yarımçıq qalan duel yenidən oynanılır.
        phase = data["phase"]
        tournament.phase = "champion" if tournament.champion else ("lobby" if phase == "lobby" else "bracket")
        return tournament
