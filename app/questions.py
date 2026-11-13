"""Sual tipləri: yoxlama, cavabın qiymətləndirilməsi və xal hesabı."""
import math
import re
import unicodedata

TYPES = ("choice", "multi", "truefalse", "text", "slider", "order", "poll", "cloud")
UNSCORED = ("poll", "cloud")
MAX_OPTIONS = 6
MAX_STREAK_BONUS = 500


class QuestionError(ValueError):
    pass


def _text(value, limit, label):
    value = str(value or "").strip()
    if not value:
        raise QuestionError(f"{label} boş ola bilməz")
    return value[:limit]


def _number(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise QuestionError(f"{label} rəqəm olmalıdır") from None
    if not math.isfinite(number):
        raise QuestionError(f"{label} rəqəm olmalıdır")
    return number


def _options(raw, minimum=2):
    options = [str(o).strip()[:120] for o in (raw.get("options") or []) if str(o).strip()]
    if not minimum <= len(options) <= MAX_OPTIONS:
        raise QuestionError(f"{minimum}–{MAX_OPTIONS} variant olmalıdır")
    return options


def _correct_indexes(raw, options):
    try:
        correct = sorted({int(i) for i in (raw.get("correct") or [])})
    except (TypeError, ValueError):
        raise QuestionError("Düzgün cavab seçilməyib") from None
    if not correct or correct[0] < 0 or correct[-1] >= len(options):
        raise QuestionError("Düzgün cavab seçilməyib")
    return correct


def clean_question(raw):
    """Redaktordan və ya AI-dan gələn sualı yoxlayıb standart formaya salır."""
    if not isinstance(raw, dict):
        raise QuestionError("Sual düzgün formatda deyil")
    kind = raw.get("type")
    if kind not in TYPES:
        raise QuestionError("Naməlum sual tipi")

    try:
        seconds = int(raw.get("time") or 20)
        points = int(raw.get("points", 1))
    except (TypeError, ValueError):
        raise QuestionError("Vaxt və xal rəqəm olmalıdır") from None

    question = {
        "type": kind,
        "text": _text(raw.get("text"), 300, "Sualın mətni"),
        "time": max(5, min(120, seconds)),
        "points": 0 if kind in UNSCORED else max(0, min(2, points)),
        "media": _upload(raw.get("media") or raw.get("image")),
        "explanation": str(raw.get("explanation") or "").strip()[:300],
    }

    if kind == "choice":
        question["options"] = _options(raw)
        question["correct"] = _correct_indexes(raw, question["options"])[:1]
    elif kind == "multi":
        question["options"] = _options(raw, 3)
        question["correct"] = _correct_indexes(raw, question["options"])
    elif kind == "truefalse":
        question["options"] = ["Doğru", "Yanlış"]
        question["correct"] = _correct_indexes(raw, question["options"])[:1]
    elif kind == "poll":
        question["options"] = _options(raw)
    elif kind == "order":
        # Variantlar düzgün ardıcıllıqla saxlanır, oyunda qarışdırılır.
        question["options"] = _options(raw, 3)
    elif kind == "text":
        accepted = [str(a).strip()[:80] for a in (raw.get("accepted") or []) if str(a).strip()]
        if not accepted:
            raise QuestionError("Ən azı bir qəbul olunan cavab yazın")
        question["accepted"] = accepted
    elif kind == "slider":
        low, high = _number(raw.get("min"), "Minimum"), _number(raw.get("max"), "Maksimum")
        answer = _number(raw.get("answer"), "Düzgün cavab")
        step = _number(raw.get("step") or 1, "Addım")
        tolerance = abs(_number(raw.get("tolerance") or 0, "Dözüm"))
        if low >= high or not low <= answer <= high or step <= 0:
            raise QuestionError("Şkala aralığı və ya düzgün cavab yanlışdır")
        question.update(min=low, max=high, step=step, answer=answer, tolerance=tolerance)
    return question


IMAGE_TYPES = ("png", "jpg", "gif", "webp")
VIDEO_TYPES = ("mp4", "webm")
UPLOAD_PATTERN = re.compile(r"/uploads/[0-9a-f]{32}\.(%s)" % "|".join(IMAGE_TYPES + VIDEO_TYPES))


def _upload(value):
    """Yalnız öz yüklədiyimiz fayllar qəbul olunur."""
    return value if isinstance(value, str) and UPLOAD_PATTERN.fullmatch(value) else None


def media_of(question):
    """Sualın şəkli və ya videosu: {"kind": "image"|"video", "url": ...} və ya None."""
    url = _upload(question.get("media") or question.get("image"))
    if not url:
        return None
    return {"kind": "video" if url.rsplit(".", 1)[1] in VIDEO_TYPES else "image", "url": url}


def fold(text):
    """Müqayisə üçün: böyük/kiçik hərf və Azərbaycan hərflərinin fərqi nəzərə alınmır."""
    text = str(text).replace("Ə", "e").replace("ə", "e").replace("ı", "i").replace("I", "i")
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def _one_typo_apart(a, b):
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:]
    return a[i:] == b[i + 1:]


def text_matches(answer, accepted):
    given = fold(answer)
    if not given:
        return False
    for option in accepted:
        target = fold(option)
        if given == target or (len(target) >= 5 and _one_typo_apart(given, target)):
            return True
    return False


def grade(question, answer, order_map=None):
    """Cavabı qiymətləndirir: (0..1 arası pay, tam düzgündürmü)."""
    kind = question["type"]
    try:
        if kind in ("choice", "truefalse"):
            hit = int(answer) in question["correct"]
            return (1.0, True) if hit else (0.0, False)
        if kind == "multi":
            picked = {int(i) for i in answer}
            right = set(question["correct"])
            share = max(0, len(picked & right) - len(picked - right)) / len(right)
            return share, picked == right
        if kind == "text":
            hit = text_matches(answer, question["accepted"])
            return (1.0, True) if hit else (0.0, False)
        if kind == "slider":
            hit = abs(float(answer) - question["answer"]) <= question["tolerance"] + 1e-9
            return (1.0, True) if hit else (0.0, False)
        if kind == "order":
            sequence = [order_map[int(i)] for i in answer]
            size = len(question["options"])
            if sorted(sequence) != list(range(size)):
                return 0.0, False
            placed = sum(1 for position, item in enumerate(sequence) if position == item)
            return placed / size, placed == size
    except (TypeError, ValueError, IndexError, KeyError):
        return 0.0, False
    return 0.0, False


def valid_answer(question, answer):
    """Oyunçunun göndərdiyi cavabın forması uyğundurmu (zibil məlumatı buraxmır)."""
    kind = question["type"]
    size = len(question.get("options", []))
    if kind in ("choice", "truefalse", "poll"):
        return isinstance(answer, int) and not isinstance(answer, bool) and 0 <= answer < size
    if kind == "multi":
        return (isinstance(answer, list) and 0 < len(answer) <= size
                and all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i < size for i in answer))
    if kind == "order":
        return (isinstance(answer, list) and all(isinstance(i, int) for i in answer)
                and sorted(answer) == list(range(size)))
    if kind in ("text", "cloud"):
        return isinstance(answer, str) and 0 < len(answer.strip()) <= 80
    if kind == "slider":
        return (isinstance(answer, (int, float)) and not isinstance(answer, bool)
                and question["min"] <= answer <= question["max"])
    return False


def speed_points(question, share, elapsed_ms):
    """Tam vaxtda bazanın yarısı, dərhal cavabda bazanın hamısı."""
    base = 1000 * question["points"]
    limit = question["time"] * 1000
    pace = 1 - 0.5 * min(1.0, max(0.0, elapsed_ms / limit))
    return int(round(base * share * pace / 10) * 10)


def streak_bonus(streak):
    return min(MAX_STREAK_BONUS, 100 * max(0, streak - 1))


def answer_label(question):
    """Düzgün cavabın oxunaqlı mətni (ekranda göstərmək üçün)."""
    kind = question["type"]
    if kind in ("choice", "multi", "truefalse"):
        return ", ".join(question["options"][i] for i in question["correct"])
    if kind == "text":
        return question["accepted"][0]
    if kind == "slider":
        return f"{question['answer']:g}"
    if kind == "order":
        return " → ".join(question["options"])
    return ""


def answer_text(question, value, order_map=None):
    """Oyunçunun verdiyi cavabın oxunaqlı mətni (AI izahçısı üçün)."""
    options = question.get("options", [])
    try:
        if question["type"] in ("choice", "truefalse", "poll"):
            return options[value]
        if question["type"] == "multi":
            return ", ".join(options[i] for i in sorted(value))
        if question["type"] == "order":
            return " → ".join(options[order_map[i]] for i in value)
    except (TypeError, IndexError, KeyError):
        return str(value)
    return str(value)
