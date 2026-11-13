"""Pley-off cədvəli: püşk, rəqibsiz keçid, qaliblərin irəliləməsi."""
import random

import pytest

from app.game import GameError
from app.questions import clean_question
from app.tournament import Tournament, round_name

QUESTIONS = [clean_question({"type": "choice", "text": f"S{i}", "options": ["a", "b"], "correct": [0]})
             for i in range(6)] + [clean_question({"type": "poll", "text": "Sorğu", "options": ["a", "b"]})]


def play_out(tournament):
    """Hər hazır matçda `a` qalib gəlir. Oynanan matçların sayını qaytarır."""
    played = 0
    while (spot := tournament.next_match()) is not None:
        r, m = spot
        tournament.record(r, m, tournament.rounds[r][m]["a"], [100, 0])
        played += 1
    return played


def entrants(count):
    tournament = Tournament("T", QUESTIONS, 3)
    for number in range(count):
        tournament.add(f"Oyunçu {number}")
    return tournament


@pytest.mark.parametrize("count", [2, 3, 5, 8, 13, 20, 32])
def test_every_size_ends_with_one_champion_after_n_minus_one_duels(count):
    tournament = entrants(count)
    tournament.draw()
    assert play_out(tournament) == count - 1
    champion = tournament.champion
    assert champion in tournament.entrants
    out = [n for n in tournament.entrants if tournament.eliminated(n)]
    assert len(out) == count - 1 and champion not in out


def test_round_names():
    assert [round_name(i, 4) for i in range(4)] == ["1/8 final", "Dörddəbir final", "Yarımfinal", "Final"]


def test_byes_never_pair_two_empty_slots():
    tournament = entrants(5)
    tournament.draw(shuffle=lambda names: None)
    first = tournament.rounds[0]
    assert [Tournament.status(m) for m in first] == ["bye", "bye", "bye", "ready"]
    assert tournament.next_match() == [0, 3]
    assert tournament.rounds[1][0]["a"] == "Oyunçu 0" and tournament.rounds[1][0]["b"] == "Oyunçu 1"


def test_winner_moves_on_and_loser_is_out():
    tournament = entrants(4)
    tournament.draw(shuffle=lambda names: None)
    first = tournament.rounds[0][0]
    assert (first["a"], first["b"]) == ("Oyunçu 0", "Oyunçu 3")
    assert tournament.opponent("Oyunçu 0") == "Oyunçu 3"
    tournament.record(0, 0, "Oyunçu 3", [200, 900])
    assert tournament.eliminated("Oyunçu 0") and not tournament.eliminated("Oyunçu 3")
    assert tournament.rounds[1][0]["a"] == "Oyunçu 3"
    assert tournament.opponent("Oyunçu 3") is None  # digər yarımfinal hələ oynanmayıb
    assert tournament.opponent("Oyunçu 0") is None


def test_result_cannot_be_written_twice_or_for_a_stranger():
    tournament = entrants(4)
    tournament.draw()
    r, m = tournament.next_match()
    with pytest.raises(GameError):
        tournament.record(r, m, "Kənar adam", [1, 0])
    tournament.record(r, m, tournament.rounds[r][m]["a"], [1, 0])
    with pytest.raises(GameError):
        tournament.record(r, m, tournament.rounds[r][m]["a"], [1, 0])


def test_registration_rules():
    tournament = Tournament("T", QUESTIONS, 3)
    assert tournament.add("  Əli ") == "Əli"
    assert tournament.add("ƏLİ") == "Əli"  # eyni adam geri qayıdır
    with pytest.raises(GameError):
        tournament.draw()  # bir nəfərlə olmaz
    tournament.add("Vəli")
    tournament.draw()
    with pytest.raises(GameError):
        tournament.add("Gec gələn")
    assert tournament.add("vəli") == "Vəli"
    assert not tournament.remove("Vəli")


def test_entrant_limit():
    tournament = entrants(32)
    with pytest.raises(GameError):
        tournament.add("33-cü")


def test_polls_are_not_used_and_match_questions_are_distinct():
    tournament = Tournament("T", QUESTIONS, 5)
    assert all(q["type"] == "choice" for q in tournament.pool)
    for _ in range(10):
        picked = tournament.take_questions(5)
        assert len({q["text"] for q in picked}) == 5
    assert len(tournament.take_questions(50)) == 6


def test_quiz_without_scored_questions_is_refused():
    with pytest.raises(GameError):
        Tournament("T", [QUESTIONS[-1]])


def test_saved_tournament_resumes_where_it_stopped():
    tournament = entrants(6)
    tournament.draw()
    r, m = tournament.next_match()
    tournament.record(r, m, tournament.rounds[r][m]["b"], [0, 10])
    tournament.phase = "match"
    again = Tournament.from_dict(tournament.to_dict())
    assert again.phase == "bracket" and again.rounds == tournament.rounds
    assert again.next_match() == tournament.next_match()
    play_out(again)
    assert Tournament.from_dict(again.to_dict()).phase == "champion"


def test_random_draw_keeps_everyone():
    random.seed(4)
    tournament = entrants(11)
    tournament.draw()
    seen = {name for m in tournament.rounds[0] for name in (m["a"], m["b"]) if name}
    assert seen == set(tournament.entrants)


def test_entrant_is_tied_to_the_phone():
    tournament = Tournament("T", QUESTIONS, 3)
    assert tournament.add("Əli", "a" * 32) == "Əli"
    assert tournament.add("tamam başqa", "a" * 32) == "Əli"  # eyni telefon
    with pytest.raises(GameError):
        tournament.add("əli", "b" * 32)  # başqasının adı
    tournament.add("Vəli", "b" * 32)
    assert tournament.rename("Vəli", "Vəlixan") == "Vəlixan" and tournament.key_of("Vəlixan") == "b" * 32
    tournament.draw()
    with pytest.raises(GameError):
        tournament.add("Əli", "c" * 32)  # püşkdən sonra yerini almaq olmaz
    assert Tournament.from_dict(tournament.to_dict()).ids == tournament.ids
