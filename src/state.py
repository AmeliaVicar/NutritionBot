import json
import os
import re
import pytz
from datetime import date, datetime
from typing import Tuple, Dict, Set, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "state.json")
TZ = "Europe/Moscow"  # или возьми из config, если у тебя так принято

def parse_until_date(text: str) -> str | None:
    """
    Ищет дату после слова "до": "уехала до 14 января", "до 14.01", "до 14/01".
    Возвращает ISO: YYYY-MM-DD
    """
    t = (text or "").lower()

    # 14.01 / 14-01 / 14/01 / 14.01.2026
    m = re.search(r"\bдо\s+(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b", t)
    if m:
        d = int(m.group(1))
        mo = int(m.group(2))
        y = m.group(3)
        if y:
            y = int(y)
            if y < 100:
                y += 2000
        else:
            y = datetime.now(pytz.timezone(TZ)).year
        try:
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except Exception:
            return None

    # "до 14 января"
    months = {
        "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5,
        "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10,
        "ноябр": 11, "декабр": 12
    }
    m2 = re.search(r"\bдо\s+(\d{1,2})\s+([а-яё]+)\b", t)
    if m2:
        d = int(m2.group(1))
        mon_word = m2.group(2)
        mo = None
        for k, v in months.items():
            if mon_word.startswith(k):
                mo = v
                break
        if mo is None:
            return None
        y = datetime.now(pytz.timezone(TZ)).year
        return f"{y:04d}-{mo:02d}-{d:02d}"

    return None

def _today_iso() -> str:
    return date.today().isoformat()


def _load() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"active": [], "excused": [], "mentions": {}, "excused_until": {}}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_sets() -> Tuple[Set[int], Set[int], Dict[str, str], Dict[str, str]]:
    """
    returns: excused, active, mentions, excused_until
    """
    data = _load()
    excused = set(map(int, data.get("excused", [])))
    active = set(map(int, data.get("active", [])))
    mentions = data.get("mentions", {})
    excused_until = data.get("excused_until", {})
    return excused, active, mentions, excused_until


def save_mention(uid: int, mention: str):
    data = _load()
    mentions = data.get("mentions", {})
    mentions[str(uid)] = mention
    data["mentions"] = mentions
    _save(data)


def mark_excused(uid: int):
    data = _load()
    s = set(map(int, data.get("excused", [])))
    s.add(uid)
    data["excused"] = list(s)
    _save(data)


def mark_active(uid: int):
    data = _load()
    s = set(map(int, data.get("active", [])))
    s.add(uid)
    data["active"] = list(s)
    _save(data)


def set_excused_until(uid: int, until_iso: str):
    data = _load()
    excused_until = data.get("excused_until", {})
    excused_until[str(uid)] = until_iso
    data["excused_until"] = excused_until
    _save(data)


def is_excused_today(uid: int) -> bool:
    """
    True если excused сегодня или excused_until не истёк.
    """
    excused, _active, _mentions, excused_until = get_sets()
    if uid in excused:
        return True

    until = excused_until.get(str(uid))
    if not until:
        return False

    try:
        until_d = date.fromisoformat(until)
        return date.today() <= until_d
    except Exception:
        return False


def cleanup_expired_excused_until():
    """
    Можно дергать раз в день, чтобы чистить старые "до даты".
    """
    data = _load()
    excused_until = data.get("excused_until", {})
    today = date.today()

    changed = False
    for k, v in list(excused_until.items()):
        try:
            d = date.fromisoformat(v)
            if d < today:
                del excused_until[k]
                changed = True
        except Exception:
            # если кривой формат — удаляем
            del excused_until[k]
            changed = True

    if changed:
        data["excused_until"] = excused_until
        _save(data)



# --- простенький парсер даты "до ..." ---
MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5,
    "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10,
    "ноябр": 11, "декабр": 12,
}


def parse_until_date(text: str) -> Optional[str]:
    """
    Ищет дату в фразах типа:
      - "уехала до 14.01"
      - "до 14.01.2026"
      - "до 14 января"
      - "до 14"  (тогда текущий месяц/год)
    Возвращает ISO YYYY-MM-DD или None
    """
    t = (text or "").lower()

    # dd.mm(.yyyy)
    m = re.search(r"до\s+(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?", t)
    if m:
        dd = int(m.group(1))
        mm = int(m.group(2))
        yy = m.group(3)
        if yy:
            yy = int(yy)
            if yy < 100:
                yy += 2000
        else:
            yy = date.today().year
        try:
            return date(yy, mm, dd).isoformat()
        except Exception:
            return None

    # "до 14 января"
    m = re.search(r"до\s+(\d{1,2})\s+([а-я]+)", t)
    if m:
        dd = int(m.group(1))
        month_word = m.group(2)
        mm = None
        for k, v in MONTHS.items():
            if month_word.startswith(k):
                mm = v
                break
        if mm is None:
            return None
        yy = date.today().year
        try:
            return date(yy, mm, dd).isoformat()
        except Exception:
            return None

    # "до 14"
    m = re.search(r"до\s+(\d{1,2})\b", t)
    if m:
        dd = int(m.group(1))
        today = date.today()
        try:
            return date(today.year, today.month, dd).isoformat()
        except Exception:
            return None

    return None

