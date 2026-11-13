"""Oyun məntiqi, xal hesabı və cavabların sızmaması."""
import json

import pytest

from app import ai
from app.game import Game, GameError
from app.questions import (QuestionError, clean_question, fold, grade, media_of, speed_points,
                           streak_bonus, text_matches, valid_answer)
from app.seed import SAMPLE


def quiz(*questions):
    return {"id": 1, "title": "Test", "questions": [clean_question(q) for q in questions]}


CHOICE = {"type": "choice", "text": "S?", "time": 10, "options": ["a", "b", "c"], "correct": [1]}


def started(*questions, players=("Aysel", "Tural")):
    game = Game(quiz(*questions), "123456")
    tokens = [game.join(name).token for name in players]
    for player in game.players.values():
        player.connected = True
    game.start()
    game.media_done()
    game.open_question(0.0)
    return game, tokens


def test_sample_quiz_is_valid():
    assert len([clean_question(q) for q in SAMPLE]) == 8


@pytest.mark.parametrize("raw", [
    {"type": "choice", "text": "", "options": ["a", "b"], "correct": [0]},
    {"type": "choice", "text": "x", "options": ["a"], "correct": [0]},
    {"type": "choice", "text": "x", "options": ["a", "b"], "correct": [5]},
    {"type": "text", "text": "x", "accepted": []},
    {"type": "slider", "text": "x", "min": 5, "max": 1, "answer": 2},
    {"type": "slider", "text": "x", "min": 0, "max": 9, "answer": "nan"},
    {"type": "nonsense", "text": "x"},
])
def test_bad_questions_are_rejected(raw):
    with pytest.raises(QuestionError):
        clean_question(raw)


def test_foreign_media_url_is_dropped():
    assert clean_question({**CHOICE, "media": "http://evil.example/x.png"})["media"] is None
    assert clean_question({**CHOICE, "media": "/uploads/../server.py"})["media"] is None


IMG = "/uploads/" + "a" * 32 + ".png"
VID = "/uploads/" + "b" * 32 + ".mp4"


def test_old_image_field_still_works_and_kind_is_detected():
    assert clean_question({**CHOICE, "image": IMG})["media"] == IMG
    assert media_of({"media": IMG}) == {"kind": "image", "url": IMG}
    assert media_of({"media": VID})["kind"] == "video"
    assert media_of({"image": None}) is None


def test_media_is_shown_before_the_question():
    game = Game(quiz({**CHOICE, "media": VID}, {**CHOICE, "media": IMG}, CHOICE), "1")
    token = game.join("A").token
    game.start()
    assert game.phase == "media"
    view = game.player_view(game.players[token], 0.0)
    assert view["question"]["media"]["kind"] == "video" and "options" not in view["question"]
    assert not game.submit(token, 1, 0.0)
    assert game.media_done() and game.phase == "intro" and not game.media_done()
    game.open_question(0.0)
    game.close_question()
    game.advance(), game.advance()
    assert game.phase == "media" and game.question["media"] == IMG
    game.media_done()
    game.open_question(0.0)
    game.close_question()
    game.advance(), game.advance()
    assert game.phase == "intro"


def test_fold_ignores_azerbaijani_letters_and_case():
    assert fold("AZƏRBAYCAN") == fold("azerbaycan") == fold("Azərbaycan")
    assert fold("İlqar") == fold("ilqar") and fold("Şəki") == fold("seki")


def test_text_answer_allows_one_typo_on_long_words_only():
    assert text_matches("Azerbaycam", ["Azərbaycan"])
    assert not text_matches("Azerbaycxx", ["Azərbaycan"])
    assert not text_matches("kat", ["pişik", "it"])
    assert not text_matches("", ["it"])


def test_speed_points_range():
    question = clean_question(CHOICE)
    assert speed_points(question, 1, 0) == 1000
    assert speed_points(question, 1, 10_000) == 500
    assert speed_points(question, 1, 99_999) == 500
    assert speed_points({**question, "points": 2}, 1, 0) == 2000


def test_streak_bonus_is_capped():
    assert [streak_bonus(n) for n in (1, 2, 3, 6, 50)] == [0, 100, 200, 500, 500]


def test_multi_partial_credit_but_not_marked_correct():
    question = clean_question({"type": "multi", "text": "x", "options": ["a", "b", "c", "d"], "correct": [0, 1]})
    assert grade(question, [0, 1]) == (1.0, True)
    assert grade(question, [0]) == (0.5, False)
    assert grade(question, [0, 2]) == (0.0, False)
    assert grade(question, [0, 1, 2, 3]) == (0.0, False)


@pytest.mark.parametrize("value", [True, "1", None, 99, -1, [1], 1.5])
def test_malformed_choice_answers_are_refused(value):
    assert not valid_answer(clean_question(CHOICE), value)


def test_slider_tolerance():
    question = clean_question({"type": "slider", "text": "x", "min": 0, "max": 100, "answer": 50, "tolerance": 2})
    assert grade(question, 52)[1] and not grade(question, 53)[1]
    assert not valid_answer(question, 101)


def test_order_answer_uses_shuffled_mapping():
    calls = iter([[2, 0, 1]])

    def shuffle(items):
        items[:] = next(calls)

    game = Game(quiz({"type": "order", "text": "x", "options": ["a", "b", "c"]}), "1", shuffle=shuffle)
    token = game.join("A").token
    game.phase, game.index = "intro", 0
    game.open_question(0.0)
    assert game.player_view(game.players[token], 1.0)["question"]["options"] == ["c", "a", "b"]
    assert game.submit(token, [1, 2, 0], 1.0)
    assert game.players[token].answers[0].correct


def test_duplicate_names_refused_and_reconnect_keeps_player():
    game = Game(quiz(CHOICE), "1")
    player = game.join("Əli")
    with pytest.raises(GameError):
        game.join("  ƏLİ ")
    assert game.join("whatever", player.token) is player


def test_kicked_name_cannot_return_and_room_has_a_limit():
    game = Game(quiz(CHOICE), "1")
    game.kick(game.join("Pis").token)
    with pytest.raises(GameError):
        game.join("pis")
    for number in range(30):
        game.join(f"P{number}")
    with pytest.raises(GameError):
        game.join("Artıq")


def test_one_answer_only_and_late_answer_refused():
    game, (a, b) = started(CHOICE)
    assert game.submit(a, 1, 1.0)
    assert not game.submit(a, 0, 2.0)
    assert not game.submit(b, 1, 10.5)


def test_score_is_hidden_until_question_closes():
    game, (a, _b) = started(CHOICE)
    game.submit(a, 1, 1.0)
    assert game.players[a].score == 0
    game.close_question()
    assert game.players[a].score == 950


def test_streak_grows_and_resets():
    game, (a, b) = started(CHOICE, CHOICE, CHOICE)
    for index, answer in enumerate((1, 1, 0)):
        game.submit(a, answer, game.opened_at)
        game.close_question()
        if index < 2:
            game.advance(), game.advance()
            game.open_question(0.0)
    assert game.players[a].score == 1000 + 1100
    assert game.players[a].streak == 0 and game.players[a].best_streak == 2


def test_poll_gives_no_points_and_keeps_streak():
    game, (a, _b) = started(CHOICE, {"type": "poll", "text": "x", "options": ["a", "b"]})
    game.submit(a, 1, 0.0)
    game.close_question()
    game.advance(), game.advance()
    game.open_question(0.0)
    game.submit(a, 0, 0.0)
    game.close_question()
    assert game.players[a].score == 1000 and game.players[a].streak == 1


def test_all_answered_ignores_offline_players():
    game, (a, b) = started(CHOICE)
    game.players[b].connected = False
    assert not game.all_answered()
    game.submit(a, 1, 0.0)
    assert game.all_answered()


def test_views_never_leak_the_answer_before_reveal():
    secret = {"type": "text", "text": "x", "accepted": ["GİZLİCAVAB"], "explanation": "İZAHMƏTNİ"}
    for raw in (CHOICE, secret, {"type": "slider", "text": "x", "min": 0, "max": 9, "answer": 7, "explanation": "İZAHMƏTNİ"}):
        game, (a, _b) = started(raw)
        for view in (game.player_view(game.players[a], 1.0), game.host_view(1.0)):
            assert "correct" not in view["question"] and "reveal" not in view
            assert "accepted" not in view["question"] and "answer" not in view["question"]
            dumped = json.dumps(view, ensure_ascii=False)
            assert "GİZLİCAVAB" not in dumped and "İZAHMƏTNİ" not in dumped


def test_order_view_does_not_reveal_order():
    game, (a, _b) = started({"type": "order", "text": "x", "options": ["a", "b", "c", "d"]})
    assert game.player_view(game.players[a], 1.0)["question"]["options"] != ["a", "b", "c", "d"]


def test_team_score_is_average_so_size_does_not_matter():
    game = Game(quiz(CHOICE), "1")
    game.configure(mode="team", team_count=2)
    tokens = [game.join(n).token for n in ("A", "B", "C")]
    game.start()
    game.open_question(0.0)
    for token in tokens:
        game.submit(token, 1, 0.0)
    game.close_question()
    assert {row["score"] for row in game.team_standings()} == {1000}
    assert sorted(row["members"] for row in game.team_standings()) == [1, 2]


def test_late_joiner_goes_to_smallest_team():
    game = Game(quiz(CHOICE), "1")
    game.configure(mode="team", team_count=2)
    for name in ("A", "B", "C"):
        game.join(name)
    game.start()
    late = game.join("D")
    assert sum(1 for p in game.players.values() if p.team == late.team) == 2


def test_ties_share_a_rank():
    game, _ = started(CHOICE)
    assert [row["rank"] for row in game.standings()] == [1, 1]


def test_flow_ends_on_podium_and_export_counts_scored_only():
    game, (a, b) = started(CHOICE, {"type": "poll", "text": "x", "options": ["a", "b"]})
    game.submit(a, 1, 0.0)
    game.close_question()
    game.advance(), game.advance()
    assert game.phase == "intro"
    game.open_question(0.0)
    game.close_question()
    game.advance(), game.advance()
    assert game.phase == "podium"
    result = game.export()
    winner = next(p for p in result["players"] if p["name"] == "Aysel")
    assert winner["rank"] == 1 and winner["correct"] == 1 and winner["scored_total"] == 1


def test_ai_prompt_carries_the_answer_and_marks_the_player_message():
    question = clean_question({**CHOICE, "explanation": "Bakı paytaxtdır"})
    prompt = ai.build_prompt(question, "b", "a", False, "Bəs Gəncə?")
    assert "Correct answer: b" in prompt and "Host's note: Bakı paytaxtdır" in prompt
    assert "The player answered: a (wrong)" in prompt
    assert prompt.endswith("<player_message>\nBəs Gəncə?\n</player_message>")
    assert "did not answer" in ai.build_prompt(question, "b", None, False, "?")


def test_ai_prefers_groq_when_its_key_is_set(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    assert ai.provider() == "groq"
    monkeypatch.delenv("GROQ_API_KEY")
    assert ai.provider() == "claude"


def test_explain_context_only_after_reveal_and_reads_the_players_answer():
    game, (a, _b) = started(CHOICE, {"type": "poll", "text": "x", "options": ["a", "b"]})
    with pytest.raises(GameError):
        game.explain_context(a, 0)  # cavab hələ açılmayıb
    game.submit(a, 0, 0.0)
    game.close_question()
    context = game.explain_context(a, 0)
    assert context["correct_answer"] == "b" and context["player_answer"] == "a" and not context["player_correct"]
    game.advance(), game.advance()
    game.open_question(0.0)
    game.close_question()
    with pytest.raises(GameError):
        game.explain_context(a, 1)  # sorğunun düzgün cavabı yoxdur
    with pytest.raises(GameError):
        game.explain_context(a, "0")


def test_order_answer_is_written_in_the_order_the_player_chose():
    calls = iter([[2, 0, 1]])
    game = Game(quiz({"type": "order", "text": "x", "options": ["a", "b", "c"]}), "1",
                shuffle=lambda items: items.__setitem__(slice(None), next(calls)))
    token = game.join("A").token
    game.start(), game.media_done()
    game.open_question(0.0)
    game.submit(token, [1, 2, 0], 1.0)
    game.close_question()
    assert game.explain_context(token, 0)["player_answer"] == "a → b → c"



PID_A, PID_B = "a" * 32, "b" * 32


def test_same_phone_gets_its_player_back_without_token():
    game = Game(quiz(CHOICE), "1")
    first = game.join("Aysel", pid=PID_A)
    assert game.join("başqa ad", pid=PID_A) is first
    with pytest.raises(GameError):
        game.join("aysel", pid=PID_B)  # eyni ad, başqa telefon
    assert first.key == PID_A


def test_kick_bans_the_phone_and_the_name():
    game = Game(quiz(CHOICE), "1")
    game.kick(game.join("Pis", pid=PID_A).token)
    with pytest.raises(GameError):
        game.join("Yeni ad", pid=PID_A)
    with pytest.raises(GameError):
        game.join("pis", pid=PID_B)


def test_rename_only_in_lobby_and_only_to_a_free_name():
    game = Game(quiz(CHOICE), "1")
    a = game.join("Aysel", pid=PID_A)
    game.join("Tural", pid=PID_B)
    with pytest.raises(GameError):
        game.rename(a.token, "TURAL")
    assert game.rename(a.token, "Ayka") == "Ayka" and a.key == PID_A
    game.start()
    with pytest.raises(GameError):
        game.rename(a.token, "Yenə")


def test_host_can_remove_and_restore_points():
    game = Game(quiz(CHOICE, CHOICE), "1")
    a = game.join("Aysel", pid=PID_A).token
    b = game.join("Tural", pid=PID_B).token
    with pytest.raises(GameError):
        game.adjust(a, -100)  # oyun başlamayıb
    game.start(), game.media_done()
    game.open_question(0.0)
    game.submit(a, 1, 0.0)
    game.submit(b, 1, 5.0)
    game.close_question()
    assert game.standings()[0]["name"] == "Aysel"
    entry = game.adjust(a, -500, "  telefona   baxdı ")
    assert entry["delta"] == -500 and entry["reason"] == "telefona baxdı" and entry["question"] == 1
    assert game.players[a].score == 500 and game.standings()[0]["name"] == "Tural"
    assert game.adjust(a, -10_000)["delta"] == -500  # 0-dan aşağı düşmür, faktiki silinən yazılır
    with pytest.raises(GameError):
        game.adjust(a, -1)  # artıq 0-dır
    assert game.adjust(a, 300)["delta"] == 300
    for bad in (0, True, "100", 1.5, 10**6):
        with pytest.raises(GameError):
            game.adjust(a, bad)
    with pytest.raises(GameError):
        game.adjust("yox", -1)
    result = game.export()
    assert [x["delta"] for x in result["adjustments"]] == [-500, -500, 300]
    assert next(p for p in result["players"] if p["name"] == "Aysel")["score"] == 300


def test_quip_context_describes_each_players_question_without_tokens():
    game, (a, b) = started(CHOICE, CHOICE)
    before = game.ranks()
    game.submit(a, 1, 1.5)
    game.close_question()
    tokens, context = game.quip_context(0, before)
    assert tokens == [a, b] and context["correct_answer"] == "b" and context["question_number"] == 1
    aysel, tural = context["players"]
    assert aysel == {"player": 1, "name": "Aysel", "answered": True, "correct": True, "partly_correct": False,
                     "answer": "b", "seconds": 1.5, "points_won": game.players[a].score, "streak": 1,
                     "rank": 1, "previous_rank": 1, "total_score": game.players[a].score}
    assert tural["answered"] is False and tural["rank"] == 2 and tural["previous_rank"] == 1
    assert a not in json.dumps(context) and b not in json.dumps(context)
    tokens, final = game.finale_context()
    assert final["players"][0]["correct"] == 1 and final["players"][1]["average_seconds"] is None


def test_ai_lines_are_validated():
    raw = json.dumps({"lines": [{"player": 1, "text": "  Əla   iş! "}, {"player": 1, "text": "təkrar"},
                                {"player": 9, "text": "yox"}, {"player": True, "text": "yox"},
                                {"player": 2, "text": ""}, "zibil"]})
    assert ai.parse_lines(raw, 2, {"text": 5}) == {1: {"text": "Əla i"}}
    with pytest.raises(ai.AIError):
        ai.parse_lines("{yarımçıq", 2, {"text": 10})


def test_ai_lines_with_gendered_or_personal_words_are_dropped():
    raw = json.dumps({"lines": [{"player": 1, "title": "Gecikən Qız", "text": "7 saniyə"},
                                {"player": 2, "title": "Sürət ustası", "text": "1.1 saniyə, şimşək!"}]})
    assert ai.parse_lines(raw, 2, {"title": 40, "text": 200}) == {2: {"title": "Sürət ustası", "text": "1.1 saniyə, şimşək!"}}
