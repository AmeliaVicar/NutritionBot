import re
from dataclasses import dataclass
from datetime import date
from typing import Literal


ManualGreenAction = Literal["set", "remove"]


GREEN_LINE_RE = re.compile(r"\bзелен\w*\s+строк\w*\b", re.IGNORECASE)
REMOVE_RE = re.compile(
    r"\b(?:убрать|убери|снять|сними|отменить|отмени|удалить|удали)\b",
    re.IGNORECASE,
)
NUMERIC_DATE_RE = re.compile(
    r"(?:\bдо\s+)?(?P<day>\d{1,2})[./](?P<month>\d{1,2})(?:[./](?P<year>\d{2,4}))?\b",
    re.IGNORECASE,
)
MONTH_DATE_RE = re.compile(
    r"(?:\bдо\s+)?(?P<day>\d{1,2})\s+(?P<month>[а-я]+)\b",
    re.IGNORECASE,
)
DAY_ONLY_DATE_RE = re.compile(r"\bдо\s+(?P<day>\d{1,2})\b", re.IGNORECASE)

MONTH_PREFIXES = (
    ("январ", 1),
    ("феврал", 2),
    ("март", 3),
    ("апрел", 4),
    ("май", 5),
    ("мая", 5),
    ("мае", 5),
    ("маю", 5),
    ("июн", 6),
    ("июл", 7),
    ("август", 8),
    ("сентябр", 9),
    ("октябр", 10),
    ("ноябр", 11),
    ("декабр", 12),
)


@dataclass(frozen=True)
class ManualGreenCommand:
    action: ManualGreenAction
    until: date | None = None

    @property
    def sheet_value(self) -> str:
        return format_manual_green_until(self.until)


def normalize_manual_green_text(text: str) -> str:
    normalized = (text or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", normalized.strip())


def format_manual_green_until(until: date | None) -> str:
    if until is None:
        return ""
    return until.strftime("%d.%m")


def parse_manual_green_command(text: str, base_date: date) -> ManualGreenCommand | None:
    normalized = normalize_manual_green_text(text)
    if not GREEN_LINE_RE.search(normalized):
        return None

    if REMOVE_RE.search(normalized):
        return ManualGreenCommand(action="remove")

    return ManualGreenCommand(
        action="set",
        until=parse_manual_green_until(normalized, base_date),
    )


def parse_manual_green_until(text: str, base_date: date) -> date | None:
    normalized = normalize_manual_green_text(text)

    numeric = NUMERIC_DATE_RE.search(normalized)
    if numeric:
        return _build_date(
            int(numeric.group("day")),
            int(numeric.group("month")),
            numeric.group("year"),
            base_date,
        )

    month_match = MONTH_DATE_RE.search(normalized)
    if month_match:
        month = _month_number(month_match.group("month"))
        if month is None:
            return None
        return _build_date(
            int(month_match.group("day")),
            month,
            None,
            base_date,
        )

    day_only = DAY_ONLY_DATE_RE.search(normalized)
    if day_only:
        return _build_date(
            int(day_only.group("day")),
            base_date.month,
            None,
            base_date,
        )

    return None


def _month_number(raw_month: str) -> int | None:
    month = normalize_manual_green_text(raw_month)
    for prefix, number in MONTH_PREFIXES:
        if month.startswith(prefix):
            return number
    return None


def _build_date(day: int, month: int, raw_year: str | None, base_date: date) -> date | None:
    year_was_explicit = bool(raw_year)
    if raw_year:
        year = int(raw_year)
        if year < 100:
            year += 2000
    else:
        year = base_date.year

    try:
        parsed = date(year, month, day)
    except ValueError:
        return None

    if not year_was_explicit and parsed < base_date:
        try:
            parsed = date(year + 1, month, day)
        except ValueError:
            return None

    return parsed
