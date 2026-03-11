import re
from typing import Optional

MEAL_COL = {
    "breakfast": "D",
    "snack1": "E",
    "lunch": "F",
    "snack2": "G",
    "dinner": "H",
}

EXCUSE_WORDS = [
    "\u0431\u0435\u0437 \u043e\u0442\u0447\u0435\u0442\u043e\u0432",
    "\u0431\u0435\u0437 \u043e\u0442\u0447\u0451\u0442\u043e\u0432",
    "\u0443\u0435\u0445\u0430\u043b",
    "\u0443\u0435\u0445\u0430\u043b\u0430",
    "\u0437\u0430\u0431\u043e\u043b\u0435\u043b",
    "\u0437\u0430\u0431\u043e\u043b\u0435\u043b\u0430",
    "\u0431\u043e\u043b\u0435\u044e",
]

SKIP_PATTERNS = [
    r"\u043d\u0435\s*\u0431\u0443\u0434\u0435\u0442\b",
    r"\b\u0431\u0435\u0437\b",
    r"\u043d\u0435\s*\u0431\u044b\u043b\u043e\b",
    r"\b\u043d\u0435\u0442\b",
    r"\b\u043f\u0440\u043e\u043f\u0443\u0441\u0442\w*\b",
]

MEAL_WORD_PATTERNS = {
    "breakfast": r"\b\u0437\u0430\u0432\u0442\u0440\u0430\u043a\w*\b",
    "lunch": r"\b\u043e\u0431\u0435\u0434\w*\b",
    "dinner": r"\b\u0443\u0436\u0438\u043d\w*\b",
}

WEIGHT_META_WORDS = [
    "\u043d\u0435\u0432\u0435\u0440",
    "\u043d\u0435 \u0432\u0435\u0440",
    "\u043d\u0435\u043f\u0440\u0430\u0432",
    "\u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u043e",
    "\u0432 \u0442\u0430\u0431\u043b\u0438\u0446",
    "\u0432 \u043e\u0442\u0447\u0435\u0442\u0435",
    "\u0432 \u043e\u0442\u0447\u0451\u0442\u0435",
    "\u0443\u043a\u0430\u0437\u0430\u043d",
    "\u0438\u0441\u043f\u0440\u0430\u0432",
    "\u043e\u0448\u0438\u0431",
]

_MEAL_TOKEN = (
    r"(?:[12]\s*)?\u043f\u0435\u0440\u0435\u043a\u0443\u0441\w*|"
    r"(?:\u043f\u0435\u0440\u0432\w+|\u0432\u0442\u043e\u0440\w+)\s+\u043f\u0435\u0440\u0435\u043a\u0443\u0441\w*|"
    r"\u043e\u0431\u043e\u0438\u0445\s+\u043f\u0435\u0440\u0435\u043a\u0443\u0441\w*|"
    r"\u0437\u0430\u0432\u0442\u0440\u0430\u043a\w*|"
    r"\u043e\u0431\u0435\u0434\w*|"
    r"\u0443\u0436\u0438\u043d\w*"
)

MEAL_MATCH_RE = re.compile(_MEAL_TOKEN, re.IGNORECASE)

MEAL_REPORT_RE = re.compile(
    rf"^\s*(?:[a-z\u0430-\u044f\u04510-9_.-]+\s*,?\s*){{0,3}}(?:(?:(?:\u0431\u0435\u0437|\u043f\u0440\u043e\u043f\u0443\u0441\u0442\w*)\s+)?(?:{_MEAL_TOKEN})|\u043d\u0435\u0442\s+(?:{_MEAL_TOKEN}))\b",
    re.IGNORECASE,
)

MEAL_REPORT_TAIL_RE = re.compile(
    rf"\b(?:{_MEAL_TOKEN})\b[^?]{{0,80}}(?:\b\u043d\u0435\u0442\b|\u043d\u0435\s*\u0431\u044b\u043b\u043e\b|\u043d\u0435\s*\u0431\u0443\u0434\u0435\u0442\b)",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    text = text.lower().replace("\u0451", "\u0435")
    return re.sub(r"\s+", " ", text.strip())


def is_excuse(text: str) -> bool:
    t = normalize(text)
    return any(word in t for word in EXCUSE_WORDS)


def is_skip(text: str) -> bool:
    t = normalize(text)
    return any(re.search(pattern, t) for pattern in SKIP_PATTERNS)


def _reported_hour(text: str) -> Optional[int]:
    t = normalize(text)
    match = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", t)
    if not match:
        return None
    return int(match.group(1))


def _has_weight_meta(text: str) -> bool:
    t = normalize(text)
    return any(word in t for word in WEIGHT_META_WORDS)


def looks_like_meal_report(text: str) -> bool:
    t = normalize(text)
    if not t or "?" in t:
        return False
    return bool(MEAL_REPORT_RE.search(t) or MEAL_REPORT_TAIL_RE.search(t))


def split_report_parts(text: str) -> list[str]:
    raw_parts = re.split(
        rf"[\r\n;]+|,\s*(?=(?:{_MEAL_TOKEN}|\u043f\u0440\u043e\u043f\u0443\u0441\u0442\w*))",
        text or "",
        flags=re.IGNORECASE,
    )
    parts = []
    for part in raw_parts:
        cleaned = part.strip()
        if cleaned:
            parts.append(cleaned)
    return parts or ([text.strip()] if text and text.strip() else [])


def looks_like_weight_report(text: str) -> bool:
    t = normalize(text)
    if not t or "?" in t or _has_weight_meta(t):
        return False
    if parse_weight_delta(t) is not None or parse_absolute_weight(t) is not None:
        return True
    return bool(re.fullmatch(r"\d{2,3}(?:\.\d{1,3})?", t))


def detect_meal(text: str, hour: int | None = None) -> Optional[str]:
    t = normalize(text)
    explicit_hour = _reported_hour(t)
    if explicit_hour is not None:
        hour = explicit_hour

    for meal, pattern in MEAL_WORD_PATTERNS.items():
        if re.search(pattern, t):
            return meal

    if re.search(r"\b\u043f\u0435\u0440\u0435\u043a\u0443\u0441\w*\b", t):
        if re.search(r"(?:\b2\b|\u043f\u0435\u0440\u0435\u043a\u0443\u0441\w*\s*2(?=\D|$)|\u043f\u0435\u0440\u0435\u043a\u0443\u0441\w*2(?=\D|$)|\b\u0432\u0442\u043e\u0440\w+\b)", t):
            return "snack2"
        if re.search(r"(?:\b1\b|\u043f\u0435\u0440\u0435\u043a\u0443\u0441\w*\s*1(?=\D|$)|\u043f\u0435\u0440\u0435\u043a\u0443\u0441\w*1(?=\D|$)|\b\u043f\u0435\u0440\u0432\w+\b)", t):
            return "snack1"
        if hour is not None:
            return "snack1" if hour < 13 else "snack2"

    return None


def extract_meal_marks(text: str, hour: int | None = None) -> list[tuple[str, str]]:
    marks: list[tuple[str, str]] = []

    for part in split_report_parts(text):
        normalized_part = normalize(part)
        explicit_hour = _reported_hour(part)
        part_hour = explicit_hour if explicit_hour is not None else hour
        matches = list(MEAL_MATCH_RE.finditer(normalized_part))

        if not matches:
            meal = detect_meal(part, hour=part_hour)
            if meal:
                marks.append((meal, "-" if is_skip(part) else "+"))
            continue

        clause_skip = is_skip(part)
        clause_positive = bool(
            re.search(
                r"\b(?:\u0431\u044b\u043b\w*|\u0431\u0443\u0434\u0435\u0442\w*|\u043f\u043e\u0435\u043b\w*|\u0441\u044a\u0435\u043b\w*)\b",
                normalized_part,
            )
        )

        if len(matches) > 1 and clause_skip and not clause_positive:
            for idx, match in enumerate(matches):
                segment_start = 0 if idx == 0 else match.start()
                segment_end = len(normalized_part) if idx + 1 == len(matches) else matches[idx + 1].start()
                segment = normalized_part[segment_start:segment_end]
                meal = detect_meal(segment, hour=part_hour)
                if meal:
                    marks.append((meal, "-"))
            continue

        for idx, match in enumerate(matches):
            snippet_start = 0 if idx == 0 else matches[idx - 1].end()
            snippet_end = len(normalized_part) if idx + 1 == len(matches) else matches[idx + 1].start()
            snippet = normalized_part[snippet_start:snippet_end]
            meal = detect_meal(snippet, hour=part_hour)
            if not meal:
                continue
            marks.append((meal, "-" if is_skip(snippet) else "+"))

    return marks


def late_message(meal: str, hour: int, minute: int) -> Optional[str]:
    total = hour * 60 + minute
    if meal == "snack1" and total > 11 * 60:
        return "\u26a0\ufe0f \u041f\u0435\u0440\u0432\u044b\u0439 \u043f\u0435\u0440\u0435\u043a\u0443\u0441 \u2014 \u0434\u043e 11:00."
    if meal == "lunch" and total > 14 * 60:
        return "\u26a0\ufe0f \u041e\u0431\u0435\u0434 \u2014 \u0434\u043e 14:00."
    if meal == "snack2" and total > 16 * 60:
        return "\u26a0\ufe0f \u0412\u0442\u043e\u0440\u043e\u0439 \u043f\u0435\u0440\u0435\u043a\u0443\u0441 \u2014 \u0434\u043e 16:00."
    return None


def parse_weight_delta(text: str) -> Optional[float]:
    t = normalize(text).replace(",", ".")
    if _has_weight_meta(t):
        return None
    if re.fullmatch(r"0(?:\.0+)?", t):
        return 0.0

    match = re.search(r"(\u043f\u043b\u044e\u0441|\u043c\u0438\u043d\u0443\u0441|\+|-)\s*(\d+(?:\.\d+)?)", t)
    if not match:
        return None

    sign = -1 if match.group(1) in ("-", "\u043c\u0438\u043d\u0443\u0441") else 1
    value = float(match.group(2))
    if "\u0433\u0440" in t or "\u0433\u0440\u0430\u043c" in t or value >= 10:
        value = value / 1000

    delta = round(sign * value, 3)
    if abs(delta) > 5:
        return None
    return delta


def parse_absolute_weight(text: str) -> Optional[float]:
    t = normalize(text).replace(",", ".")
    if _has_weight_meta(t):
        return None
    if any(token in t for token in ["+", "-", "\u043c\u0438\u043d\u0443\u0441", "\u043f\u043b\u044e\u0441", "\u0433\u0440", "\u0433\u0440\u0430\u043c"]):
        return None
    if any(re.search(pattern, t) for pattern in list(MEAL_WORD_PATTERNS.values()) + [r"\b\u043f\u0435\u0440\u0435\u043a\u0443\u0441\w*\b"]):
        return None

    has_weight_word = bool(re.search(r"\b\u0432\u0435\u0441\b", t))
    if not has_weight_word and not re.fullmatch(r"\d{2,3}(?:\.\d{1,3})?", t):
        return None

    match = re.search(r"\b(\d{2,3}(?:\.\d{1,3})?)\b", t)
    if not match:
        return None

    value = float(match.group(1))
    if 30 <= value <= 200:
        return round(value, 3)
    return None
