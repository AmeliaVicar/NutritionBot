import json
import os
import re
from datetime import date
from typing import Dict, Optional, Set, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "state.json")


def _new_group_state() -> dict:
    return {
        "active": [],
        "excused": [],
        "mentions": {},
        "excused_until": {},
        "users": {},
    }


def _load_all() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def _save_all(data: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_group(data: dict, chat_id: int) -> dict:
    key = str(chat_id)
    if key not in data or not isinstance(data.get(key), dict):
        data[key] = _new_group_state()
    else:
        group = data[key]
        group.setdefault("active", [])
        group.setdefault("excused", [])
        group.setdefault("mentions", {})
        group.setdefault("excused_until", {})
        group.setdefault("users", {})
    return data[key]


def get_sets(chat_id: int) -> Tuple[Set[int], Set[int], Dict[str, str], Dict[str, str]]:
    data = _load_all()
    group = _get_group(data, chat_id)
    excused = set(map(int, group.get("excused", [])))
    active = set(map(int, group.get("active", [])))
    mentions = group.get("mentions", {})
    excused_until = group.get("excused_until", {})
    return excused, active, mentions, excused_until


def save_mention(chat_id: int, uid: int, mention: str):
    data = _load_all()
    group = _get_group(data, chat_id)
    group["mentions"][str(uid)] = mention
    _save_all(data)


def save_user(chat_id: int, uid: int, username: str | None, full_name: str | None):
    data = _load_all()
    group = _get_group(data, chat_id)
    group["users"][str(uid)] = {
        "username": (username or "").strip(),
        "full_name": (full_name or "").strip(),
    }
    _save_all(data)


def get_users(chat_id: int) -> Dict[str, Dict[str, str]]:
    data = _load_all()
    group = _get_group(data, chat_id)
    users = group.get("users", {})
    users = users if isinstance(users, dict) else {}

    mentions = group.get("mentions", {})
    if isinstance(mentions, dict):
        for uid in mentions:
            users.setdefault(str(uid), {"username": "", "full_name": ""})

    return users


def mark_excused(chat_id: int, uid: int):
    data = _load_all()
    group = _get_group(data, chat_id)
    excused = set(map(int, group.get("excused", [])))
    excused.add(uid)
    group["excused"] = list(excused)
    _save_all(data)


def mark_active(chat_id: int, uid: int):
    data = _load_all()
    group = _get_group(data, chat_id)

    active = set(map(int, group.get("active", [])))
    active.add(uid)
    group["active"] = list(active)

    excused = set(map(int, group.get("excused", [])))
    if uid in excused:
        excused.discard(uid)
        group["excused"] = list(excused)

    if str(uid) in group.get("excused_until", {}):
        del group["excused_until"][str(uid)]

    _save_all(data)


def remove_excused(chat_id: int, uid: int):
    data = _load_all()
    group = _get_group(data, chat_id)

    excused = set(map(int, group.get("excused", [])))
    if uid in excused:
        excused.discard(uid)
        group["excused"] = list(excused)

    if str(uid) in group.get("excused_until", {}):
        del group["excused_until"][str(uid)]

    _save_all(data)


def set_excused_until(chat_id: int, uid: int, until_iso: str):
    data = _load_all()
    group = _get_group(data, chat_id)
    group["excused_until"][str(uid)] = until_iso
    _save_all(data)


def is_excused_today(chat_id: int, uid: int) -> bool:
    excused, _active, _mentions, excused_until = get_sets(chat_id)

    if uid in excused:
        return True

    until = excused_until.get(str(uid))
    if not until:
        return False

    try:
        until_date = date.fromisoformat(until)
        return date.today() <= until_date
    except Exception:
        return False


def cleanup_expired_excused_until(chat_id: int):
    data = _load_all()
    group = _get_group(data, chat_id)

    excused_until = group.get("excused_until", {})
    today = date.today()

    changed = False
    for key, value in list(excused_until.items()):
        try:
            parsed = date.fromisoformat(value)
            if parsed < today:
                del excused_until[key]
                changed = True
        except Exception:
            del excused_until[key]
            changed = True

    if changed:
        group["excused_until"] = excused_until
        _save_all(data)


MONTHS = {
    "\u044f\u043d\u0432\u0430\u0440": 1,
    "\u0444\u0435\u0432\u0440\u0430\u043b": 2,
    "\u043c\u0430\u0440\u0442": 3,
    "\u0430\u043f\u0440\u0435\u043b": 4,
    "\u043c\u0430": 5,
    "\u0438\u044e\u043d": 6,
    "\u0438\u044e\u043b": 7,
    "\u0430\u0432\u0433\u0443\u0441\u0442": 8,
    "\u0441\u0435\u043d\u0442\u044f\u0431\u0440": 9,
    "\u043e\u043a\u0442\u044f\u0431\u0440": 10,
    "\u043d\u043e\u044f\u0431\u0440": 11,
    "\u0434\u0435\u043a\u0430\u0431\u0440": 12,
}


def parse_until_date(text: str) -> Optional[str]:
    normalized = (text or "").lower().replace("\u0451", "\u0435")

    match = re.search(r"\u0434\u043e\s+(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?", normalized)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year_raw = match.group(3)
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        else:
            year = date.today().year
        try:
            return date(year, month, day).isoformat()
        except Exception:
            return None

    match = re.search(r"\u0434\u043e\s+(\d{1,2})\s+([\u0430-\u044f]+)", normalized)
    if match:
        day = int(match.group(1))
        month_word = match.group(2)

        month = None
        for prefix, number in MONTHS.items():
            if month_word.startswith(prefix):
                month = number
                break
        if month is None:
            return None

        year = date.today().year
        try:
            return date(year, month, day).isoformat()
        except Exception:
            return None

    match = re.search(r"\u0434\u043e\s+(\d{1,2})\b", normalized)
    if match:
        day = int(match.group(1))
        today = date.today()
        try:
            return date(today.year, today.month, day).isoformat()
        except Exception:
            return None

    return None
