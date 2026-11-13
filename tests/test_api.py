"""HTTP icazələri, canlı otaq, hesabat və reytinq."""
import time

import pytest
from fastapi.testclient import TestClient

from app import db, server


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(server, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(server.library, "LIBRARY", tmp_path / "viktorinalar")
    monkeypatch.setattr(server, "INTRO_SECONDS", 0)
    monkeypatch.setattr(server, "IMAGE_SECONDS", 0)
    monkeypatch.setattr(server, "is_local", lambda c: c.headers.get("x-test-remote") is None)
    server.rooms.clear()
    with TestClient(server.app) as test_client:
        yield test_client


QUIZ = {"title": "Sınaq", "questions": [
    {"type": "choice", "text": "S1", "time": 10, "options": ["a", "b"], "correct": [1]}]}


def play_until(ws, phase):
    while True:
        view = ws.receive_json()
        if view.get("phase") == phase:
            return view


def test_admin_api_refuses_remote_clients(client):
    headers = {"x-test-remote": "1"}
    assert client.get("/api/quizzes", headers=headers).status_code == 403
    assert client.post("/api/quizzes", json=QUIZ, headers=headers).status_code == 403
    assert client.get("/admin", headers=headers).status_code == 403
    assert client.get("/api/leaderboard", headers=headers).status_code == 403
    assert client.get("/", headers=headers).status_code == 200


def test_origin_check_blocks_other_sites():
    assert not server.same_origin({"origin": "http://evil.example", "host": "localhost:8020"})
    assert server.same_origin({"origin": "http://localhost:8020", "host": "localhost:8020"})
    assert server.same_origin({"host": "localhost:8020"})


def test_quiz_validation_message_names_question(client):
    response = client.post("/api/quizzes", json={"title": "x", "questions": [{"type": "choice", "text": ""}]})
    assert response.status_code == 400 and "Sual 1" in response.json()["error"]


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
MP4 = b"\x00\x00\x00\x18ftypisom" + b"0" * 64
MOV = b"\x00\x00\x00\x14ftypqt  " + b"0" * 64
WEBM = b"\x1aE\xdf\xa3" + b"0" * 64


def upload(client, name, data):
    return client.post("/api/upload", files={"file": (name, data, "application/octet-stream")})


def test_upload_checks_content_not_the_file_name(client):
    assert upload(client, "a.png", b"<svg onload=alert(1)>").status_code == 400
    assert upload(client, "a.mp4", MOV).status_code == 400
    image = upload(client, "a.png", PNG).json()
    assert image["kind"] == "image" and image["url"].endswith(".png")
    video = upload(client, "x.bin", MP4).json()
    assert video["kind"] == "video" and video["url"].endswith(".mp4")
    assert upload(client, "x.webm", WEBM).json()["url"].endswith(".webm")
    # Video irəli-geri çəkilə bilsin deyə statik fayllar hissə-hissə verilməlidir.
    served = client.get("/static/style.css", headers={"Range": "bytes=0-9"})
    assert served.status_code == 206 and len(served.content) == 10


def test_too_big_upload_is_refused_and_not_kept(client, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "MAX_IMAGE_BYTES", 100)
    monkeypatch.setattr(server, "UPLOAD_CHUNK", 32)
    assert upload(client, "a.png", PNG + b"0" * 5000).status_code == 413
    assert not list((tmp_path / "uploads").iterdir())


def test_video_waits_for_stage_then_question_opens(client):
    video = upload(client, "v.webm", WEBM).json()["url"]
    quiz = {"title": "Video", "questions": [{**QUIZ["questions"][0], "media": video}]}
    quiz_id = client.post("/api/quizzes", json=quiz).json()["id"]
    pin = client.post("/api/rooms", json={"quiz_id": quiz_id}).json()["pin"]
    with client.websocket_connect(f"/ws/host/{pin}") as host, client.websocket_connect(f"/ws/play/{pin}") as one:
        one.send_json({"name": "Aysel"})
        play_until(one, "lobby")
        host.send_json({"action": "start"})
        view = play_until(one, "media")
        assert view["question"]["media"] == {"kind": "video", "url": video}
        assert "options" not in view["question"]
        host.send_json({"action": "media_done"})
        assert play_until(one, "question")["question"]["options"] == ["a", "b"]


def test_image_moves_on_by_itself(client):
    image = upload(client, "a.png", PNG).json()["url"]
    quiz = {"title": "Şəkil", "questions": [{**QUIZ["questions"][0], "media": image}]}
    quiz_id = client.post("/api/quizzes", json=quiz).json()["id"]
    pin = client.post("/api/rooms", json={"quiz_id": quiz_id}).json()["pin"]
    with client.websocket_connect(f"/ws/host/{pin}") as host, client.websocket_connect(f"/ws/play/{pin}") as one:
        one.send_json({"name": "Aysel"})
        play_until(one, "lobby")
        host.send_json({"action": "start"})
        assert play_until(one, "media")["question"]["media"]["kind"] == "image"
        assert play_until(one, "question")["question"]["media"]["url"] == image


def test_quiz_generation_endpoint_is_gone(client):
    assert client.post("/api/ai/generate", data={"topic": "x"}).status_code in (404, 405)


def test_unknown_room(client):
    assert client.get("/api/rooms/000000").status_code == 404


def test_full_game_saves_report_and_leaderboard(client):
    quiz_id = client.post("/api/quizzes", json=QUIZ).json()["id"]
    pin = client.post("/api/rooms", json={"quiz_id": quiz_id}).json()["pin"]
    with client.websocket_connect(f"/ws/host/{pin}") as host, \
            client.websocket_connect(f"/ws/play/{pin}") as one, \
            client.websocket_connect(f"/ws/play/{pin}") as two:
        one.send_json({"name": "Aysel"})
        assert play_until(one, "lobby")["me"]["name"] == "Aysel"
        two.send_json({"name": "=Tural"})
        play_until(two, "lobby")
        host.send_json({"action": "start"})
        view = play_until(one, "question")
        assert "correct" not in view["question"]
        play_until(two, "question")
        one.send_json({"answer": 1})
        two.send_json({"answer": 0})
        result = play_until(one, "reveal")["result"]
        assert result["correct"] and result["points"] >= 500
        assert play_until(two, "reveal")["result"]["correct"] is False
        host.send_json({"action": "next"})
        host.send_json({"action": "next"})
        final = play_until(host, "podium")
        assert final["standings"][0]["name"] == "Aysel"
        assert final["game_id"]

    game_id = client.get("/api/games").json()[0]["id"]
    report = client.get(f"/api/games/{game_id}").json()
    assert report["questions"][0]["accuracy"] == 50
    text = client.get(f"/api/games/{game_id}/csv").text
    assert text.startswith("﻿") and "'=Tural" in text

    board = client.get("/api/leaderboard").json()
    assert board["all"][0]["name"] == "Aysel" and board["all"][0]["wins"] == 1
    assert board["all"][0]["badges"][0]["id"] == "first_win"
    assert len(board["week"]) == 2

    assert client.delete(f"/api/games/{game_id}").status_code == 200
    assert client.get("/api/leaderboard").json()["all"] == []


def test_reconnect_keeps_score_and_answer(client):
    quiz_id = client.post("/api/quizzes", json=QUIZ).json()["id"]
    pin = client.post("/api/rooms", json={"quiz_id": quiz_id}).json()["pin"]
    with client.websocket_connect(f"/ws/host/{pin}") as host:
        with client.websocket_connect(f"/ws/play/{pin}") as first:
            first.send_json({"name": "Aysel"})
            token = play_until(first, "lobby")["me"]["token"]
        with client.websocket_connect(f"/ws/play/{pin}") as again:
            again.send_json({"token": token})
            view = play_until(again, "lobby")
            assert view["me"]["name"] == "Aysel" and view["me"]["players"] == 1
        host.send_json({"action": "finish"})
        assert play_until(host, "podium")


def test_week_start_is_monday_midnight():
    moment = time.mktime((2026, 11, 5, 15, 30, 0, 0, 0, -1))
    start = time.localtime(db.week_start(moment))
    assert (start.tm_wday, start.tm_hour, start.tm_min, start.tm_mday) == (0, 0, 0, 2)


def test_tournament_from_registration_to_champion(client):
    quiz_id = client.post("/api/quizzes", json=QUIZ).json()["id"]
    created = client.post("/api/tournaments", json={"title": "Kubok", "quiz_id": quiz_id, "per_match": 1}).json()
    pin = created["pin"]
    assert client.get(f"/api/rooms/{pin}").json()["title"] == "Kubok"
    names = ["Aysel", "Tural", "Nərmin"]
    with client.websocket_connect(f"/ws/host/{pin}") as host, \
            client.websocket_connect(f"/ws/play/{pin}") as p1, \
            client.websocket_connect(f"/ws/play/{pin}") as p2, \
            client.websocket_connect(f"/ws/play/{pin}") as p3:
        phones = dict(zip(names, (p1, p2, p3)))
        for name, ws in phones.items():
            ws.send_json({"name": name})
            assert play_until(ws, "t_lobby")["me"]["name"] == name
        host.send_json({"action": "config", "auto": False})
        host.send_json({"action": "draw"})
        view = play_until(host, "bracket")
        assert len(view["bracket"]) == 2 and view["next_round"] == "Yarımfinal"

        def duel(winner):
            host.send_json({"action": "start_match"})
            live = play_until(host, "match")
            a, b = live["duel"]["a"], live["duel"]["b"]
            assert live["match"]["phase"] in ("intro", "question")
            for name in (a, b):
                play_until(phones[name], "question")
            phones[a].send_json({"answer": 1 if a == winner else 0})
            phones[b].send_json({"answer": 1 if b == winner else 0})
            while (current := host.receive_json())["phase"] == "match" and current["match"]["phase"] != "reveal":
                pass
            host.send_json({"action": "next"})  # reveal -> board
            host.send_json({"action": "next"})  # board -> nəticə
            result = play_until(host, "result")["result"]
            assert result["winner"] == winner and result["loser"] in (a, b)
            loser_view = play_until(phones[result["loser"]], "t_result")
            assert loser_view["out"] is True
            host.send_json({"action": "next"})
            return a, b

        r, m = view["next"]
        match = view["bracket"][r]["matches"][m]
        duel(match["a"])
        final = play_until(host, "bracket")
        r, m = final["next"]
        fa = final["bracket"][r]["matches"][m]
        assert final["next_round"] == "Final"
        # Finalda rəqib gəlmir: aparıcı texniki qələbə verir.
        host.send_json({"action": "walkover", "winner": fa["b"]})
        assert play_until(host, "result")["result"]["note"] == "Texniki qələbə"
        host.send_json({"action": "next"})
        champion = play_until(host, "champion")["champion"]
        assert champion == fa["b"]
        assert play_until(phones[champion], "t_champion")["champion"] == champion

    listed = client.get("/api/tournaments").json()[0]
    assert listed["champion"] == champion and listed["phase"] == "champion"
    detail = client.get(f"/api/tournaments/{created['id']}").json()
    assert detail["bracket"][-1]["matches"][0]["winner"] == champion


def test_tournament_tie_goes_to_sudden_death(client):
    quiz = {"title": "S", "questions": [{**QUIZ["questions"][0], "text": f"S{i}"} for i in range(4)]}
    quiz_id = client.post("/api/quizzes", json=quiz).json()["id"]
    pin = client.post("/api/tournaments", json={"title": "K", "quiz_id": quiz_id, "per_match": 1}).json()["pin"]
    with client.websocket_connect(f"/ws/host/{pin}") as host, \
            client.websocket_connect(f"/ws/play/{pin}") as one, client.websocket_connect(f"/ws/play/{pin}") as two:
        one.send_json({"name": "A"})
        two.send_json({"name": "B"})
        play_until(one, "t_lobby"), play_until(two, "t_lobby")
        host.send_json({"action": "config", "auto": False})
        host.send_json({"action": "draw"})
        play_until(host, "bracket")
        host.send_json({"action": "start_match"})
        play_until(one, "question"), play_until(two, "question")
        one.send_json({"answer": 0})
        two.send_json({"answer": 0})  # ikisi də səhv: 0 : 0
        play_until(one, "reveal")
        host.send_json({"action": "next"})
        host.send_json({"action": "next"})
        # Giriş ekranı 0 saniyəyə keçdiyi üçün birbaşa əlavə sual gözlənilir.
        while (view := one.receive_json())["phase"] != "question" or view["index"] != 1:
            pass
        assert view["duel"]["sudden"] == 1 and view["total"] == 2


def test_tournament_needs_scored_questions(client):
    poll = {"title": "P", "questions": [{"type": "poll", "text": "x", "options": ["a", "b"]}]}
    quiz_id = client.post("/api/quizzes", json=poll).json()["id"]
    response = client.post("/api/tournaments", json={"title": "K", "quiz_id": quiz_id, "per_match": 3})
    assert response.status_code == 400


def test_no_sample_quiz_is_created_on_start(client):
    assert client.get("/api/quizzes").json() == []


def test_quiz_export_then_import_round_trip(client):
    from app.seed import SAMPLE
    quiz_id = client.post("/api/quizzes", json={"title": "Hamısı", "questions": SAMPLE}).json()["id"]
    exported = client.get(f"/api/quizzes/{quiz_id}/export")
    assert "attachment" in exported.headers["content-disposition"]
    data = exported.content
    single = client.post("/api/quizzes/import", files={"file": ("q.json", data, "application/json")}).json()
    assert len(single["ids"]) == 1 and single["count"] == len(SAMPLE)
    copy = client.get(f"/api/quizzes/{single['ids'][0]}").json()
    assert copy["questions"] == client.get(f"/api/quizzes/{quiz_id}").json()["questions"]
    many = b"\xef\xbb\xbf[" + data + b"," + data + b"]"  # Excel/Notepad BOM ilə saxlaya bilər
    assert len(client.post("/api/quizzes/import", files={"file": ("q.json", many, "application/json")}).json()["ids"]) == 2


def test_import_rejects_bad_files_and_writes_nothing(client):
    good = {"title": "Yaxşı", "questions": QUIZ["questions"]}
    bad = {"title": "Pis", "questions": [{"type": "choice", "text": "x", "options": ["a"], "correct": [0]}]}
    import json as _json
    response = client.post("/api/quizzes/import", files={"file": ("q.json", _json.dumps([good, bad]).encode(), "application/json")})
    assert response.status_code == 400 and "2-ci viktorina" in response.json()["error"]
    assert client.post("/api/quizzes/import", files={"file": ("q.json", b"{yarim", "application/json")}).status_code == 400
    assert client.post("/api/quizzes/import", files={"file": ("q.json", b"[]", "application/json")}).status_code == 400
    assert client.get("/api/quizzes").json() == []


def test_leaderboard_follows_the_phone_not_the_name(client):
    quiz_id = client.post("/api/quizzes", json=QUIZ).json()["id"]
    for name in ("Aysel", "Ayka"):  # eyni telefon, iki oyunda fərqli ad
        pin = client.post("/api/rooms", json={"quiz_id": quiz_id}).json()["pin"]
        with client.websocket_connect(f"/ws/host/{pin}") as host, \
                client.websocket_connect(f"/ws/play/{pin}") as me, client.websocket_connect(f"/ws/play/{pin}") as other:
            me.send_json({"name": name, "pid": "a" * 32})
            other.send_json({"name": "Aysel" if name == "Ayka" else "Tural", "pid": "b" * 32})
            play_until(me, "lobby"), play_until(other, "lobby")
            host.send_json({"action": "start"})
            play_until(me, "question")
            play_until(other, "question")
            me.send_json({"answer": 1})
            other.send_json({"answer": 0})
            play_until(me, "reveal")
            host.send_json({"action": "finish"})
            play_until(host, "podium")
    rows = {row["key"]: row for row in client.get("/api/leaderboard").json()["all"]}
    assert rows["a" * 32]["games"] == 2 and rows["a" * 32]["name"] == "Ayka"
    assert rows["b" * 32]["games"] == 2


def test_phone_rejoins_by_id_and_can_rename_in_lobby(client):
    quiz_id = client.post("/api/quizzes", json=QUIZ).json()["id"]
    pin = client.post("/api/rooms", json={"quiz_id": quiz_id}).json()["pin"]
    with client.websocket_connect(f"/ws/host/{pin}") as host:
        with client.websocket_connect(f"/ws/play/{pin}") as first:
            first.send_json({"name": "Aysel", "pid": "a" * 32})
            play_until(first, "lobby")
        with client.websocket_connect(f"/ws/play/{pin}") as again:
            again.send_json({"name": "", "pid": "a" * 32})  # token itib, ad yoxdur
            assert play_until(again, "lobby")["me"]["name"] == "Aysel"
            again.send_json({"rename": "Ayka"})
            while (view := again.receive_json()).get("me", {}).get("name") != "Ayka":
                pass
            assert view["me"]["players"] == 1
        with client.websocket_connect(f"/ws/play/{pin}") as thief:
            thief.send_json({"name": "Ayka", "pid": "c" * 32})
            assert thief.receive_json()["phase"] == "refused"



def ask_game(client):
    quiz_id = client.post("/api/quizzes", json=QUIZ).json()["id"]
    return client.post("/api/rooms", json={"quiz_id": quiz_id}).json()["pin"]


def test_player_asks_why_after_reveal(client, monkeypatch):
    seen = {}

    async def fake_explain(**kwargs):
        seen.update(kwargs)
        return "Çünki b düzgündür."
    monkeypatch.setattr(server.ai, "explain", fake_explain)
    pin = ask_game(client)
    with client.websocket_connect(f"/ws/host/{pin}") as host, client.websocket_connect(f"/ws/play/{pin}") as me:
        me.send_json({"name": "Aysel", "pid": "a" * 32})
        play_until(me, "lobby")
        host.send_json({"action": "start"})
        play_until(me, "question")
        me.send_json({"ask": {"index": 0, "text": "Niyə?"}})  # cavab açılmamış: rədd
        while "ai" not in (msg := me.receive_json()):
            pass
        assert "açılmayıb" in msg["ai"]["error"]
        me.send_json({"answer": 0})
        play_until(me, "reveal")
        me.send_json({"ask": {"index": 0, "text": "  Niyə   b? "}})
        while "ai" not in (msg := me.receive_json()):
            pass
        assert msg["ai"] == {"index": 0, "question": "Niyə b?", "answer": "Çünki b düzgündür."}
        assert seen["correct_answer"] == "b" and seen["player_answer"] == "a" and seen["message"] == "  Niyə   b? "
        host.send_json({"action": "next"})
        host.send_json({"action": "next"})
        review = play_until(me, "podium")["review"]
        assert review == [{"index": 0, "text": "S1", "answer": "b", "correct": False}]


def test_ask_without_key_gives_a_clear_message(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    pin = ask_game(client)
    with client.websocket_connect(f"/ws/host/{pin}") as host, client.websocket_connect(f"/ws/play/{pin}") as me:
        me.send_json({"name": "Aysel"})
        play_until(me, "lobby")
        host.send_json({"action": "start"})
        play_until(me, "question")
        me.send_json({"answer": 1})
        play_until(me, "reveal")
        me.send_json({"ask": {"index": 0, "text": "?"}})
        while "ai" not in (msg := me.receive_json()):
            pass
        assert "GROQ_API_KEY" in msg["ai"]["error"]


def test_ask_limit_per_player(client, monkeypatch):
    async def fake_explain(**kwargs):
        return "ok"
    monkeypatch.setattr(server.ai, "explain", fake_explain)
    monkeypatch.setattr(server, "MAX_QUESTIONS_TO_AI", 2)
    pin = ask_game(client)
    with client.websocket_connect(f"/ws/host/{pin}") as host, client.websocket_connect(f"/ws/play/{pin}") as me:
        me.send_json({"name": "Aysel"})
        play_until(me, "lobby")
        host.send_json({"action": "start"})
        play_until(me, "question")
        me.send_json({"answer": 1})
        play_until(me, "reveal")
        replies = []
        for _ in range(3):
            me.send_json({"ask": {"index": 0, "text": "?"}})
            while "ai" not in (msg := me.receive_json()):
                pass
            replies.append(msg["ai"])
        assert [r.get("answer") for r in replies[:2]] == ["ok", "ok"] and "ən çox 2" in replies[2]["error"]


def test_host_removes_points_during_and_after_the_game(client):
    pin = ask_game(client)
    with client.websocket_connect(f"/ws/host/{pin}") as host, \
            client.websocket_connect(f"/ws/play/{pin}") as me, client.websocket_connect(f"/ws/play/{pin}") as other:
        me.send_json({"name": "Aysel", "pid": "a" * 32})
        other.send_json({"name": "Tural", "pid": "b" * 32})
        token = play_until(me, "lobby")["me"]["token"]
        play_until(other, "lobby")
        host.send_json({"action": "adjust", "token": token, "delta": -100})  # lobbidə olmaz
        while "error" not in (msg := host.receive_json()):
            pass
        assert "başlamayıb" in msg["error"]
        host.send_json({"action": "start"})
        play_until(me, "question"), play_until(other, "question")
        me.send_json({"answer": 1})
        other.send_json({"answer": 1})
        play_until(me, "reveal")
        host.send_json({"action": "adjust", "token": token, "delta": -400, "reason": "köçürdü"})
        while "toast" not in (msg := me.receive_json()):
            pass
        assert msg == {"toast": "Aparıcı xalını dəyişdi: -400 (köçürdü)", "bad": True}
        while True:
            view = host.receive_json()
            row = next((p for p in view.get("players", []) if p["token"] == token), None)
            if row and view["phase"] == "reveal":
                break
        host.send_json({"action": "next"})
        host.send_json({"action": "next"})
        final = play_until(host, "podium")
        first_id = final["game_id"]
        before = next(r["score"] for r in final["standings"] if r["name"] == "Aysel")
        # Oyundan sonra da: bütün xalı silinir, nəticə yenidən yazılır.
        host.send_json({"action": "adjust", "token": token, "zero": True, "reason": "ədalətsizlik"})
        while True:
            view = host.receive_json()
            assert "error" not in view, view
            if next(r["score"] for r in view["standings"] if r["name"] == "Aysel") == 0:
                break
        assert view["game_id"] == first_id and before > 0  # eyni oyun yenidən yazılır
    games = client.get("/api/games").json()
    assert len(games) == 1 and games[0]["winner"] == "Tural"
    report = client.get(f"/api/games/{games[0]['id']}").json()
    assert [(a["delta"], a["reason"]) for a in report["adjustments"]] == [(-400, "köçürdü"), (-before, "ədalətsizlik")]
    assert client.get("/api/leaderboard").json()["all"][0]["name"] == "Tural"
    csv_text = client.get(f"/api/games/{games[0]['id']}/csv").text
    assert "Aparıcı düzəlişi" in csv_text and f"-{400 + before}" in csv_text


def test_host_adjusts_points_inside_a_tournament_duel(client):
    quiz_id = client.post("/api/quizzes", json=QUIZ).json()["id"]
    pin = client.post("/api/tournaments", json={"title": "K", "quiz_id": quiz_id, "per_match": 1}).json()["pin"]
    with client.websocket_connect(f"/ws/host/{pin}") as host, \
            client.websocket_connect(f"/ws/play/{pin}") as one, client.websocket_connect(f"/ws/play/{pin}") as two:
        one.send_json({"name": "A", "pid": "a" * 32})
        two.send_json({"name": "B", "pid": "b" * 32})
        play_until(one, "t_lobby"), play_until(two, "t_lobby")
        host.send_json({"action": "config", "auto": False})
        host.send_json({"action": "draw"})
        play_until(host, "bracket")
        host.send_json({"action": "start_match"})
        play_until(one, "question"), play_until(two, "question")
        one.send_json({"answer": 1})
        two.send_json({"answer": 1})
        live = play_until(one, "reveal")
        token = live["me"]["token"]
        host.send_json({"action": "adjust", "token": token, "zero": True})
        while True:
            view = host.receive_json()
            if view.get("duel") and view["duel"]["score"][[view["duel"]["a"], view["duel"]["b"]].index("A")] == 0:
                break


def test_phone_shows_everything_without_a_stage(client):
    pin = ask_game(client)
    with client.websocket_connect(f"/ws/host/{pin}") as host, \
            client.websocket_connect(f"/ws/play/{pin}") as me, client.websocket_connect(f"/ws/play/{pin}") as other:
        me.send_json({"name": "Aysel"})
        other.send_json({"name": "Tural"})
        play_until(other, "lobby")
        while len((view := me.receive_json()).get("roster", [])) < 2:
            pass
        assert view["roster"] == ["Aysel", "Tural"]
        host.send_json({"action": "start"})
        play_until(me, "question"), play_until(other, "question")
        me.send_json({"answer": 1})
        other.send_json({"answer": 0})
        reveal = play_until(me, "reveal")
        assert reveal["reveal"]["counts"] == [1, 1] and reveal["reveal"]["correct"] == [1]
        host.send_json({"action": "next"})
        board = play_until(me, "board")
        assert [row["name"] for row in board["standings"]] == ["Aysel", "Tural"]
        assert "token" not in board["standings"][0]


def test_tournament_spectator_watches_the_duel(client):
    quiz_id = client.post("/api/quizzes", json=QUIZ).json()["id"]
    pin = client.post("/api/tournaments", json={"title": "K", "quiz_id": quiz_id, "per_match": 1}).json()["pin"]
    with client.websocket_connect(f"/ws/host/{pin}") as host, client.websocket_connect(f"/ws/play/{pin}") as a, \
            client.websocket_connect(f"/ws/play/{pin}") as b, client.websocket_connect(f"/ws/play/{pin}") as c:
        phones = {"A": a, "B": b, "C": c}
        for name, ws in phones.items():
            ws.send_json({"name": name})
            play_until(ws, "t_lobby")
        host.send_json({"action": "config", "auto": False})
        host.send_json({"action": "draw"})
        view = play_until(host, "bracket")
        r, m = view["next"]
        match = view["bracket"][r]["matches"][m]
        spectator = next(n for n in phones if n not in (match["a"], match["b"]))
        assert play_until(phones[spectator], "t_bracket")["bracket"]
        host.send_json({"action": "start_match"})
        while True:
            seen = phones[spectator].receive_json()
            if seen["phase"] == "t_match" and seen["watch"] and seen["watch"]["phase"] == "question":
                break
        assert seen["watch"]["question"]["text"] == "S1" and "correct" not in seen["watch"]["question"]
        assert "reveal" not in seen["watch"]


def test_players_get_funny_lines_after_each_question_and_at_the_end(client, monkeypatch):
    calls = []

    async def fake_quips(context):
        calls.append(("quip", context))
        return {p["player"]: {"text": f"{p['name']}: {'əla' if p['correct'] else 'növbəti dəfə'}"} for p in context["players"]}

    async def fake_finale(context):
        calls.append(("finale", context))
        return {1: {"title": "Sürət şeytanı", "text": "Hamını qabaqladın"}}
    monkeypatch.setattr(server.ai, "quips", fake_quips)
    monkeypatch.setattr(server.ai, "finale", fake_finale)
    monkeypatch.setattr(server.ai, "configured", lambda: True)
    pin = ask_game(client)
    with client.websocket_connect(f"/ws/host/{pin}") as host, \
            client.websocket_connect(f"/ws/play/{pin}") as me, client.websocket_connect(f"/ws/play/{pin}") as other:
        me.send_json({"name": "Aysel"})
        other.send_json({"name": "Tural"})
        play_until(me, "lobby"), play_until(other, "lobby")
        lobby = play_until(host, "lobby")
        assert lobby["ai_ready"] and lobby["jokes"]
        host.send_json({"action": "start"})
        play_until(me, "question"), play_until(other, "question")
        me.send_json({"answer": 1})
        other.send_json({"answer": 0})
        while "quip" not in (msg := me.receive_json()):
            pass
        assert msg["quip"] == {"index": 0, "text": "Aysel: əla"}
        while "quip" not in (msg := other.receive_json()):
            pass
        assert msg["quip"]["text"] == "Tural: növbəti dəfə"
        host.send_json({"action": "next"})
        host.send_json({"action": "next"})
        while "finale" not in (msg := me.receive_json()):
            pass
        assert msg["finale"] == {"title": "Sürət şeytanı", "text": "Hamını qabaqladın"}
    assert [kind for kind, _ in calls] == ["quip", "finale"]


def test_host_can_switch_jokes_off(client, monkeypatch):
    async def boom(context):
        raise AssertionError("zarafat bağlı olmalı idi")
    monkeypatch.setattr(server.ai, "quips", boom)
    monkeypatch.setattr(server.ai, "finale", boom)
    monkeypatch.setattr(server.ai, "configured", lambda: True)
    pin = ask_game(client)
    with client.websocket_connect(f"/ws/host/{pin}") as host, client.websocket_connect(f"/ws/play/{pin}") as me:
        me.send_json({"name": "Aysel"})
        play_until(me, "lobby")
        host.send_json({"action": "config", "jokes": False})
        while (view := host.receive_json()).get("jokes") is not False:
            pass
        host.send_json({"action": "start"})
        play_until(me, "question")
        me.send_json({"answer": 1})
        play_until(me, "reveal")
        host.send_json({"action": "finish"})
        play_until(me, "podium")


def test_ai_failure_does_not_break_the_game(client, monkeypatch):
    async def broken(context):
        raise server.ai.AIError("limit")
    monkeypatch.setattr(server.ai, "quips", broken)
    monkeypatch.setattr(server.ai, "configured", lambda: True)
    pin = ask_game(client)
    with client.websocket_connect(f"/ws/host/{pin}") as host, client.websocket_connect(f"/ws/play/{pin}") as me:
        me.send_json({"name": "Aysel"})
        play_until(me, "lobby")
        host.send_json({"action": "start"})
        play_until(me, "question")
        me.send_json({"answer": 1})
        assert play_until(me, "reveal")["result"]["correct"]
        host.send_json({"action": "next"})
        assert play_until(me, "board")


def test_ready_quizzes_folder_is_loaded_once_without_overwriting(tmp_path, monkeypatch):
    import json as _json
    from app import library
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    folder = tmp_path / "viktorinalar"
    folder.mkdir()
    (folder / "a.json").write_text(_json.dumps({"title": "Hazır", "questions": QUIZ["questions"]}), encoding="utf-8")
    (folder / "pis.json").write_text('{"title": "Pis", "questions": [{"type": "choice", "text": ""}]}', encoding="utf-8")
    (folder / "qirıq.json").write_text("{yarım", encoding="utf-8")
    db.init()
    added, problems = library.load(folder)
    assert added == ["Hazır"] and len(problems) == 2
    quiz_id = db.list_quizzes()[0]["id"]
    db.save_quiz("Hazır", "paneldə dəyişdi", QUIZ["questions"] * 2, quiz_id)
    assert library.load(folder) == ([], problems)  # ikinci açılış: təkrar yoxdur, redaktə qalır
    assert db.get_quiz(quiz_id)["description"] == "paneldə dəyişdi" and len(db.list_quizzes()) == 1


def test_shipped_quizzes_are_valid():
    import json
    from app import library
    for file in library.LIBRARY.glob("*.json"):
        data = json.loads(file.read_text(encoding="utf-8-sig"))
        for item in data if isinstance(data, list) else [data]:
            assert item["title"] and [server.clean_question(q) for q in item["questions"]]
