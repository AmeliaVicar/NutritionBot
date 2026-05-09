import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Sequence

from sheets import UID_INDEX, normalize_uid_value


MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}

NAME_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)?")
NUMERIC_DATE_RE = re.compile(
    r"(?<!\d)(?P<day>[0-3]?\d)[./](?P<month>[01]?\d)(?:[./](?P<year>\d{2,4}))?(?!\d)"
)
WORD_DATE_RE = re.compile(
    r"(?<!\d)(?P<day>[0-3]?\d)\s+(?P<month>[а-яё]+)(?:\s+(?P<year>\d{2,4}))?",
    re.IGNORECASE,
)
START_RE = re.compile(
    r"\b(?:начина\w*|старт\w*|захожу|вхожу|выхожу|иду|с\s+\d{1,2}(?:[./]|\s+[а-яё]))",
    re.IGNORECASE,
)

STOPWORDS = {
    "я",
    "мы",
    "буду",
    "будем",
    "будет",
    "начинаю",
    "начинаем",
    "начинает",
    "начать",
    "начало",
    "старт",
    "стартую",
    "стартуем",
    "стартует",
    "с",
    "со",
    "от",
    "марафон",
    "марафона",
    "добрый",
    "доброе",
    "день",
    "вечер",
    "утро",
    "здравствуйте",
    "привет",
}

INSTRUCTION_RE = re.compile(
    r"\b(?:напишите|пишите|пример|формат|фамилия|имя|команда|скан|scan|начинаете|начинают)\b",
    re.IGNORECASE,
)
REPORT_WORD_RE = re.compile(
    r"\b(?:завтрак\w*|обед\w*|ужин\w*|перекус\w*|вес)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StartCandidate:
    full_name: str
    start_date: date


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower().replace("ё", "е"))


def _format_name_token(token: str) -> str:
    parts = token.strip("-").split("-")
    return "-".join(part[:1].upper() + part[1:].lower() for part in parts if part)


def _resolve_year(day: int, month: int, year_raw: str | None, base_date: date) -> Optional[date]:
    if year_raw:
        year = int(year_raw)
        if year < 100:
            year += 2000
    else:
        year = base_date.year

    try:
        parsed = date(year, month, day)
    except ValueError:
        return None

    if not year_raw and parsed < base_date:
        try:
            parsed = date(year + 1, month, day)
        except ValueError:
            return None

    return parsed


def _month_from_word(raw_month: str) -> Optional[int]:
    month_word = _norm(raw_month)
    for prefix, number in MONTHS.items():
        if month_word.startswith(prefix):
            return number
    return None


def _find_start_date(text: str, base_date: date) -> tuple[Optional[date], Optional[tuple[int, int]]]:
    numeric = NUMERIC_DATE_RE.search(text)
    if numeric:
        parsed = _resolve_year(
            int(numeric.group("day")),
            int(numeric.group("month")),
            numeric.group("year"),
            base_date,
        )
        return parsed, numeric.span()

    word = WORD_DATE_RE.search(text)
    if word:
        month = _month_from_word(word.group("month"))
        if month is None:
            return None, None
        parsed = _resolve_year(int(word.group("day")), month, word.group("year"), base_date)
        return parsed, word.span()

    return None, None


def _name_tokens(raw: str) -> list[str]:
    tokens = []
    for token in NAME_TOKEN_RE.findall(raw or ""):
        normalized = _norm(token)
        if len(normalized) < 2 or normalized in STOPWORDS:
            continue
        tokens.append(_format_name_token(token))
    return tokens


def parse_start_candidate(text: str, base_date: date | None = None) -> Optional[StartCandidate]:
    raw = (text or "").strip()
    if not raw or raw.startswith("/") or "?" in raw:
        return None

    normalized = _norm(raw)
    if INSTRUCTION_RE.search(normalized) or REPORT_WORD_RE.search(normalized):
        return None

    base = base_date or date.today()
    start_date, date_span = _find_start_date(raw, base)
    if start_date is None or date_span is None:
        return None

    start_match = START_RE.search(normalized)
    date_start, date_end = date_span
    cut_end = date_start
    if start_match:
        cut_end = min(cut_end, start_match.start())

    name_area = raw[:cut_end]
    tokens = _name_tokens(name_area)

    if len(tokens) < 2:
        without_date = raw[:date_start] + " " + raw[date_end:]
        tokens = _name_tokens(START_RE.sub(" ", without_date))

    if len(tokens) < 2:
        return None

    if not start_match and len(tokens) != 2:
        return None

    selected = tokens[-2:] if start_match else tokens[:2]
    return StartCandidate(full_name=" ".join(selected), start_date=start_date)


def start_date_sheet_value(start_date: date, today: date | None = None) -> str:
    base = today or date.today()
    if start_date <= base + timedelta(days=1):
        return ""
    return start_date.strftime("%d.%m")


def name_key(full_name: str) -> tuple[str, ...]:
    tokens = _name_tokens(full_name)
    return tuple(_norm(token) for token in tokens[:2])


def names_match(left: str, right: str) -> bool:
    left_key = name_key(left)
    right_key = name_key(right)
    if len(left_key) < 2 or len(right_key) < 2:
        return False
    return left_key == right_key or set(left_key) == set(right_key)


def existing_uids_from_rows(rows: Sequence[Sequence[object]]) -> set[str]:
    uids: set[str] = set()
    for row in rows:
        if len(row) <= UID_INDEX:
            continue
        uid = normalize_uid_value(row[UID_INDEX])
        if uid:
            uids.add(uid)
    return uids


def find_row_by_candidate_name(
    rows: Sequence[Sequence[object]],
    full_name: str,
) -> tuple[Optional[int], str]:
    for row_number, row in enumerate(rows, start=2):
        row_name = str(row[0]).strip() if row else ""
        if not row_name or not names_match(row_name, full_name):
            continue

        row_uid = normalize_uid_value(row[UID_INDEX]) if len(row) > UID_INDEX else ""
        return row_number, row_uid

    return None, ""
