"""SQLite: viktorinalar, bitmiş oyunlar və daimi reytinq."""
import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta
from collections import Counter
from pathlib import Path

from .questions import fold

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "tralala.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS quizzes (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  questions TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS games (
  id INTEGER PRIMARY KEY, quiz_id INTEGER, title TEXT NOT NULL, pin TEXT NOT NULL, mode TEXT NOT NULL,
  questions TEXT NOT NULL, closed TEXT NOT NULL, teams TEXT NOT NULL,
  player_count INTEGER NOT NULL, started_at REAL, ended_at REAL NOT NULL,
  adjustments TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS game_players (
  game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  player_key TEXT NOT NULL, name TEXT NOT NULL, team TEXT, score INTEGER NOT NULL, rank INTEGER NOT NULL,
  correct INTEGER NOT NULL, answered INTEGER NOT NULL, scored_total INTEGER NOT NULL,
  best_streak INTEGER NOT NULL, total_ms INTEGER NOT NULL, perfect INTEGER NOT NULL,
  PRIMARY KEY (game_id, player_key));
CREATE TABLE IF NOT EXISTS answers (
  game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  q_index INTEGER NOT NULL, player_key TEXT NOT NULL, value TEXT NOT NULL,
  correct INTEGER NOT NULL, points INTEGER NOT NULL, elapsed_ms INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_gp_key ON game_players(player_key);
CREATE TABLE IF NOT EXISTS tournaments (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, quiz_id INTEGER, state TEXT NOT NULL, champion TEXT,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
"""


def connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init():
    with closing(connect()) as conn, conn:
        conn.executescript(SCHEMA)
        # Köhnə bazalarda xal düzəlişləri sütunu yoxdur.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(games)")}
        if "adjustments" not in columns:
            conn.execute("ALTER TABLE games ADD COLUMN adjustments TEXT NOT NULL DEFAULT '[]'")


# --- viktorinalar ------------------------------------------------------
def list_quizzes():
    with closing(connect()) as conn:
        rows = conn.execute("SELECT * FROM quizzes ORDER BY updated_at DESC").fetchall()
    return [{"id": r["id"], "title": r["title"], "description": r["description"],
             "count": len(json.loads(r["questions"])), "updated_at": r["updated_at"]} for r in rows]


def get_quiz(quiz_id):
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
    if not row:
        return None
    return {**dict(row), "questions": json.loads(row["questions"])}


def save_quiz(title, description, questions, quiz_id=None):
    now = time.time()
    payload = json.dumps(questions, ensure_ascii=False)
    with closing(connect()) as conn, conn:
        if quiz_id is None:
            cursor = conn.execute(
                "INSERT INTO quizzes (title, description, questions, created_at, updated_at) VALUES (?,?,?,?,?)",
                (title, description, payload, now, now))
            return cursor.lastrowid
        cursor = conn.execute("UPDATE quizzes SET title=?, description=?, questions=?, updated_at=? WHERE id=?",
                              (title, description, payload, now, quiz_id))
        return quiz_id if cursor.rowcount else None


def delete_quiz(quiz_id):
    with closing(connect()) as conn, conn:
        return conn.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,)).rowcount > 0


def quiz_count():
    with closing(connect()) as conn:
        return conn.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0]


# --- oyunlar -----------------------------------------------------------
def save_game(result, replace_id=None):
    """Bitmiş oyunu yazır. `replace_id` verilsə (oyundan sonra xal düzəlişi), köhnə qeyd eyni əməliyyatda silinir."""
    with closing(connect()) as conn, conn:
        if replace_id is not None:
            conn.execute("DELETE FROM games WHERE id = ?", (replace_id,))
        game_id = conn.execute(
            "INSERT INTO games (quiz_id, title, pin, mode, questions, closed, teams, player_count,"
            " started_at, ended_at, adjustments) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (result["quiz_id"], result["title"], result["pin"], result["mode"],
             json.dumps(result["questions"], ensure_ascii=False), json.dumps(result["closed"]),
             json.dumps(result["teams"], ensure_ascii=False), len(result["players"]),
             result["started_at"], result["ended_at"],
             json.dumps(result.get("adjustments", []), ensure_ascii=False))).lastrowid
        conn.executemany(
            "INSERT INTO game_players VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(game_id, p["key"], p["name"], p["team"], p["score"], p["rank"], p["correct"], p["answered"],
              p["scored_total"], p["best_streak"], p["total_ms"], int(p["perfect"])) for p in result["players"]])
        conn.executemany(
            "INSERT INTO answers VALUES (?,?,?,?,?,?,?)",
            [(game_id, a["index"], a["key"], json.dumps(a["value"], ensure_ascii=False), int(a["correct"]),
              a["points"], a["elapsed_ms"]) for a in result["answers"]])
    return game_id


def list_games():
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT g.id, g.title, g.mode, g.player_count, g.ended_at, json_array_length(g.closed) AS played,"
            " (SELECT name FROM game_players p WHERE p.game_id = g.id ORDER BY rank, name LIMIT 1) AS winner"
            " FROM games g ORDER BY g.ended_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_game(game_id):
    with closing(connect()) as conn:
        game = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if not game:
            return None
        players = conn.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY rank, name",
                               (game_id,)).fetchall()
        answers = conn.execute("SELECT * FROM answers WHERE game_id = ?", (game_id,)).fetchall()
    data = dict(game)
    data["questions"] = json.loads(data["questions"])
    data["closed"] = json.loads(data["closed"])
    data["teams"] = json.loads(data["teams"])
    data["adjustments"] = json.loads(data["adjustments"])
    data["players"] = [dict(p) for p in players]
    data["answers"] = [{**dict(a), "value": json.loads(a["value"])} for a in answers]
    return data


def delete_game(game_id):
    with closing(connect()) as conn, conn:
        return conn.execute("DELETE FROM games WHERE id = ?", (game_id,)).rowcount > 0


# --- reytinq -----------------------------------------------------------
BADGES = (
    ("first_win", "İlk qələbə", lambda s: s["wins"] >= 1),
    ("hat_trick", "Üç qələbə", lambda s: s["wins"] >= 3),
    ("veteran", "10 oyun", lambda s: s["games"] >= 10),
    ("perfect", "Səhvsiz oyun", lambda s: s["perfect"] >= 1),
    ("streak", "5 ardıcıl", lambda s: s["best_streak"] >= 5),
    ("fast", "Şimşək", lambda s: s["answered"] >= 20 and s["avg_ms"] < 4000),
    ("champion", "Turnir çempionu", lambda s: s["titles"] >= 1),
)


def week_start(now=None):
    moment = datetime.fromtimestamp(now if now is not None else time.time())
    monday = (moment - timedelta(days=moment.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.timestamp()


def leaderboard(since=None):
    """Oyunçular adla tanınır. Qələbə üçün oyunda ən azı 2 nəfər olmalıdır."""
    query = """
      SELECT p.player_key AS key,
             (SELECT x.name FROM game_players x JOIN games y ON y.id = x.game_id
              WHERE x.player_key = p.player_key ORDER BY y.ended_at DESC LIMIT 1) AS name,
             SUM(p.score) AS score, COUNT(*) AS games,
             SUM(p.rank = 1 AND g.player_count >= 2) AS wins, SUM(p.correct) AS correct,
             SUM(p.answered) AS answered, SUM(p.scored_total) AS asked, SUM(p.total_ms) AS total_ms,
             MAX(p.best_streak) AS best_streak, SUM(p.perfect) AS perfect
      FROM game_players p JOIN games g ON g.id = p.game_id
      WHERE g.ended_at >= ? GROUP BY p.player_key ORDER BY score DESC, wins DESC, name"""
    with closing(connect()) as conn:
        rows = conn.execute(query, (since or 0,)).fetchall()
        titles = Counter(
            json.loads(state).get("ids", {}).get(champion) or fold(champion)
            for champion, state in conn.execute(
                "SELECT champion, state FROM tournaments WHERE champion IS NOT NULL AND updated_at >= ?",
                (since or 0,)))
    table = []
    for position, row in enumerate(rows, start=1):
        stats = dict(row)
        stats["rank"] = position
        stats["accuracy"] = round(100 * stats["correct"] / stats["asked"]) if stats["asked"] else 0
        stats["avg_ms"] = round(stats["total_ms"] / stats["answered"]) if stats["answered"] else 0
        stats["titles"] = titles[stats["key"]]
        stats["badges"] = [{"id": b, "label": label} for b, label, rule in BADGES if rule(stats)]
        table.append(stats)
    return table


# --- turnirlər ---------------------------------------------------------
def create_tournament(title, quiz_id, state):
    now = time.time()
    with closing(connect()) as conn, conn:
        return conn.execute(
            "INSERT INTO tournaments (title, quiz_id, state, champion, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (title, quiz_id, json.dumps(state, ensure_ascii=False), None, now, now)).lastrowid


def save_tournament(tournament_id, state, champion):
    with closing(connect()) as conn, conn:
        conn.execute("UPDATE tournaments SET state = ?, champion = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), champion, time.time(), tournament_id))


def get_tournament(tournament_id):
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,)).fetchone()
    return {**dict(row), "state": json.loads(row["state"])} if row else None


def list_tournaments():
    with closing(connect()) as conn:
        rows = conn.execute("SELECT * FROM tournaments ORDER BY updated_at DESC").fetchall()
    result = []
    for row in rows:
        state = json.loads(row["state"])
        result.append({"id": row["id"], "title": row["title"], "champion": row["champion"],
                       "entrants": len(state["entrants"]), "phase": state["phase"],
                       "updated_at": row["updated_at"]})
    return result


def delete_tournament(tournament_id):
    with closing(connect()) as conn, conn:
        return conn.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,)).rowcount > 0
