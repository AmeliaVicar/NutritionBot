import json
import os
import re
from datetime import date
from typing import Tuple, Dict, Set, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "state.json")

def _new_group_state() -> dict:
    # важно: новые объекты, не copy()
    return {
        "active": [],
        "excused": [],
        "mentions": {},
        "excused_until": {}
    }

def _load_all() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            # если файл битый — не падаем
            return {}

def _save_all(data: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _get_group(data: dict, chat_id: int) -> dict:
    key = str(chat_id)
    if key not in data or not isinstance(data.get(key), dict):
        data[key] = _new_group_state()
    else:
        # миграция/самовосстановление ключей, если вдруг старый формат
        g = data[key]
        g.setdefault("active", [])
        g.setdefault("excused", [])
        g.setdefault("mentions", {})
        g.setdefault("excused_until", {})
    return data[key]

def get_sets(chat_id: int) -> Tuple[Set[int], Set[int], Dict[str, str], Dict[str, str]]:
    data = _load_all()
    g = _get_group(data, chat_id)
    excused = set(map(int, g.get("excused", [])))
    active = set(map(int, g.get("active", [])))
    mentions = g.get("mentions", {})
    excused_until = g.get("excused_until", {})
    return excused, active, mentions, excused_until

def save_mention(chat_id: int, uid: int, mention: str):
    data = _load_all()
    g = _get_group(data, chat_id)
    g["mentions"][str(uid)] = mention
    _save_all(data)

def mark_excused(chat_id: int, uid: int):
    data = _load_all()
    g = _get_group(data, chat_id)
    s = set(map(int, g.get("excused", [])))
    s.add(uid)
    g["excused"] = list(s)
    _save_all(data)

def mark_active(chat_id: int, uid: int):
    data = _load_all()
    g = _get_group(data, chat_id)

    s = set(map(int, g.get("active", [])))
    s.add(uid)
    g["active"] = list(s)

    # логика здравого смысла: если активен — точно не "без отчётов"
    exc = set(map(int, g.get("excused", [])))
    if uid in exc:
        exc.discard(uid)
        g["excused"] = list(exc)

    # и "уехала до ..." тоже снимаем, если человек начал отчитываться
    if str(uid) in g.get("excused_until", {}):
        del g["excused_until"][str(uid)]

    _save_all(data)

def remove_excused(chat_id: int, uid: int):
    # то, чего тебе не хватало для снятия зелёного
    data = _load_all()
    g = _get_group(data, chat_id)

    exc = set(map(int, g.get("excused", [])))
    if uid in exc:
        exc.discard(uid)
        g["excused"] = list(exc)

    if str(uid) in g.get("excused_until", {}):
        del g["excused_until"][str(uid)]

    _save_all(data)

def set_excused_until(chat_id: int, uid: int, until_iso: str):
    data = _load_all()
    g = _get_group(data, chat_id)
    g["excused_until"][str(uid)] = until_iso
    _save_all(data)

def is_excused_today(chat_id: int, uid: int) -> bool:
    excused, _active, _mentions, excused_until = get_sets(chat_id)

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

def cleanup_expired_excused_until(chat_id: int):
    data = _load_all()
    g = _get_group(data, chat_id)

    excused_until = g.get("excused_until", {})
    today = date.today()

    changed = False
    for k, v in list(excused_until.items()):
        try:
            d = date.fromisoformat(v)
            if d < today:
                del excused_until[k]
                changed = True
        except Exception:
            del excused_until[k]
            changed = True

    if changed:
        g["excused_until"] = excused_until
        _save_all(data)

# parse_until_date (оставил твою логику, только чуть подчистил)
MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5,
    "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10,
    "ноябр": 11, "декабр": 12,
}

def parse_until_date(text: str) -> Optional[str]:
    t = (text or "").lower()

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

    m = re.search(r"до\s+(\d{1,2})\s+([а-яё]+)", t)
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

    m = re.search(r"до\s+(\d{1,2})\b", t)
    if m:
        dd = int(m.group(1))
        today = date.today()
        try:
            return date(today.year, today.month, dd).isoformat()
        except Exception:
            return None

    return None