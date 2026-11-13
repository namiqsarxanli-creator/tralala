"""Hazır viktorinalar: `viktorinalar/` qovluğundakı fayllar server açılanda panelə əlavə olunur.

Paneldə eyni adlı viktorina artıq varsa, ona toxunulmur: aparıcının paneldə etdiyi dəyişikliklər itmir.
Paneldən silinən viktorinanın faylı qovluqda qalarsa, növbəti açılışda yenidən əlavə olunur."""
import json
import logging
from pathlib import Path

from . import db
from .questions import QuestionError, clean_question

LIBRARY = Path(__file__).resolve().parent.parent / "viktorinalar"
log = logging.getLogger("tralala")


def load(folder=None):
    folder = Path(folder or LIBRARY)
    existing = {quiz["title"].casefold() for quiz in db.list_quizzes()}
    added, problems = [], []
    for file in sorted(folder.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8-sig"))
            for item in data if isinstance(data, list) else [data]:
                title = str(item.get("title") or "").strip()[:80]
                if not title:
                    raise ValueError("viktorinanın adı yoxdur")
                if title.casefold() in existing:
                    continue
                questions = [clean_question(question) for question in item["questions"]]
                if not questions:
                    raise ValueError(f"“{title}” viktorinasında sual yoxdur")
                db.save_quiz(title, str(item.get("description") or "").strip()[:200], questions)
                existing.add(title.casefold())
                added.append(title)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, QuestionError) as error:
            problems.append(f"{file.name}: {error}")
            log.warning("Viktorina faylı əlavə olunmadı: %s: %s", file.name, error)
    return added, problems
