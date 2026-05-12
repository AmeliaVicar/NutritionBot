import asyncio
import html
import os
import re
import traceback
from datetime import date, datetime

import pytz
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery,
    FSInputFile,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import *
from enrollment import (
    existing_uids_from_rows,
    find_row_by_candidate_name,
    parse_start_candidate,
    start_date_sheet_value,
)
from manual_green import (
    format_manual_green_until,
    parse_manual_green_command,
)
from parser import (
    detect_meal,
    is_skip,
    is_excuse,
    late_message,
    looks_like_meal_report,
    looks_like_weight_report,
    needs_weight_keyword_warning,
    needs_weight_value_warning,
    extract_meal_marks,
    parse_explicit_weight,
    parse_sheet_weight,
    parse_weight_delta,
)
from report_status import report_row_status, red_report_uids
from sheets import Sheets, GREEN, RED, DEFAULT_EXPORT_SCALE, normalize_uid_value
from exporter import pdf_to_jpeg
from schedule_utils import staggered_daily_time
from state import (
    mark_active, mark_excused, get_sets, save_mention, save_user, get_users,
    set_excused_until, is_excused_today, parse_until_date, cleanup_expired_excused_until, remove_excused,
    save_start_candidate, get_start_candidates, mark_start_candidate_imported,
    cleanup_expired_manual_green, get_manual_green, remove_manual_green,
    set_manual_green,
)

# -------------------------
# 0) Инициализация
# -------------------------
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

_sheets_cache : dict[int, Sheets] = {}

def get_sc(chat_id : int) -> Sheets:
    if chat_id not in GROUPS:
        raise KeyError(f"Unknown chay_id={chat_id}. Add it to config.CROUPS")
    if chat_id not in _sheets_cache:
        cfg = GROUPS[chat_id]
        _sheets_cache[chat_id] = Sheets(
            cfg["SPREADSHEET_ID"],
            cfg["SHEET_NAME"],
            export_scale=cfg.get("EXPORT_SCALE", DEFAULT_EXPORT_SCALE),
        )
    return _sheets_cache[chat_id]

def is_admin(chat_id: int, uid: int) -> bool:
    cfg = GROUPS.get(chat_id, {})
    admins = cfg.get("ADMINS", set())
    return uid in admins

tz = pytz.timezone(TZ)

REPORT_HOUR = 20
REPORT_MINUTE = 0
REPORT_STAGGER_MINUTES = 3
REPORT_MISFIRE_GRACE_SECONDS = 10 * 60

ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "menus"
)

print("🔥 NEW VERSION WITH SYRNIKI AND FIXED WEIGHT 🔥")

# -------------------------
# Таблица (важно: совпадает с parser.MEAL_COL, но тут оставим отдельно)
# A surname, B weight, C diff, D breakfast, E snack1, F lunch, G snack2, H dinner, ... J uid
# -------------------------
MEAL_TO_COL = {
    "breakfast": "D",
    "snack1": "E",
    "lunch": "F",
    "snack2": "G",
    "dinner": "H",
}

# -------------------------
# Утилиты
# -------------------------
def get_msg_text(m: Message) -> str:
    # важно: caption тоже читаем
    return (m.text or m.caption or "").strip()


def looks_like_weight_or_delta(text: str) -> bool:
    return looks_like_weight_report(text)


def message_is_report(text: str) -> bool:
    """Return True only for messages that look like actual reports."""
    if not text or text.startswith("/"):
        return False

    if is_excuse(text):
        return True
    if looks_like_meal_report(text):
        return True
    if looks_like_weight_or_delta(text):
        return True

    return False

from aiogram.filters import Command

@dp.message(Command("reportnow"))
async def report_now(m: Message):
    if not m.from_user:
        return

    if m.from_user.id not in ADMIN_IDS:
        await m.reply("⛔️ У тебя нет доступа к этой команде.")
        return

    await m.reply("⏳ Формирую отчёт...")
    await report(m.chat.id)
    await m.reply("✅ Отчёт отправлен.")

@dp.message(Command("dump_users"))
async def dump_users(m: Message):
    if not m.from_user:
        return

    if m.from_user.id not in ADMIN_IDS:
        await m.reply("⛔ У тебя нет доступа к этой команде.")
        return

    command_parts = (m.text or "").split(maxsplit=1)
    target_chat_id = m.chat.id

    if m.chat.type == "private":
        if len(command_parts) < 2:
            await m.reply("В личке укажи chat_id группы: <code>/dump_users -1001234567890</code>")
            return
        try:
            target_chat_id = int(command_parts[1].strip())
        except ValueError:
            await m.reply("Не смогла разобрать chat_id. Пример: <code>/dump_users -1001234567890</code>")
            return

    users = get_users(target_chat_id)
    if not users:
        await m.reply("По этой группе пока нет сохранённых user_id.")
        return

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(tz).strftime("%Y%m%d_%H%M%S")
    dump_path = os.path.join(out_dir, f"users_{target_chat_id}_{stamp}.csv")

    with open(dump_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("user_id,username,full_name\n")
        for uid, info in sorted(users.items(), key=lambda item: int(item[0])):
            username = str(info.get("username", "")).replace('"', '""')
            full_name = str(info.get("full_name", "")).replace('"', '""')
            f.write(f'{uid},"{username}","{full_name}"\n')

    try:
        await bot.send_document(
            m.from_user.id,
            FSInputFile(dump_path),
            caption=f"Выгрузка user_id для chat_id {target_chat_id}",
        )
    except TelegramForbiddenError:
        await m.reply("Я не могу написать тебе в личные сообщения. Сначала открой диалог с ботом и нажми /start.")
        return

    if m.chat.type == "private":
        await m.reply(f"Отправила файл в эту же личку для chat_id {target_chat_id}.")
    else:
        await m.reply("Отправила файл тебе в личные сообщения с ботом.")

def mention_for_uid(uid: int, mentions: dict[str, str], users: dict[str, dict[str, str]]) -> str:
    saved_mention = mentions.get(str(uid))
    if saved_mention:
        return saved_mention

    user = users.get(str(uid), {})
    username = (user.get("username") or "").strip().lstrip("@")
    if username:
        return f"@{username}"

    full_name = html.escape((user.get("full_name") or "участник").strip() or "участник")
    return f'<a href="tg://user?id={uid}">{full_name}</a>'

def mention_from_user(user) -> str:
    if getattr(user, "username", None):
        return "@" + user.username

    safe_name = html.escape((getattr(user, "full_name", None) or "участник").strip() or "участник")
    return f'<a href="tg://user?id={user.id}">{safe_name}</a>'

def remember_chat_user(chat_id: int, user) -> bool:
    if chat_id not in GROUPS or not user or getattr(user, "is_bot", False):
        return False

    uid = int(user.id)
    save_mention(chat_id, uid, mention_from_user(user))
    save_user(chat_id, uid, getattr(user, "username", None), getattr(user, "full_name", None))
    return True

def saved_user_name(info: dict) -> str:
    full_name = str(info.get("full_name", "")).strip()
    if full_name:
        return full_name

    username = str(info.get("username", "")).strip().lstrip("@")
    if username:
        return f"@{username}"

    return ""

def telegram_user_display_name(user) -> str:
    full_name = (getattr(user, "full_name", None) or "").strip()
    if full_name:
        return full_name

    username = (getattr(user, "username", None) or "").strip().lstrip("@")
    if username:
        return f"@{username}"

    return "участник"

def manual_green_entry_is_active(entry: dict[str, str] | None, today: date) -> bool:
    if entry is None:
        return False

    until = str(entry.get("until", "") or "").strip()
    if not until:
        return True

    try:
        return today <= date.fromisoformat(until)
    except Exception:
        return False

def manual_green_entry_sheet_value(entry: dict[str, str] | None) -> str:
    if entry is None:
        return ""

    until = str(entry.get("until", "") or "").strip()
    if not until:
        return ""

    try:
        return format_manual_green_until(date.fromisoformat(until))
    except Exception:
        return ""

def resolve_manual_green_target(m: Message):
    replied = getattr(m, "reply_to_message", None)
    replied_user = getattr(replied, "from_user", None) if replied is not None else None

    if replied_user is None or getattr(replied_user, "is_bot", False):
        return m.from_user, None

    if replied_user.id == m.from_user.id:
        return replied_user, None

    if m.from_user.id in ADMIN_IDS or is_admin(m.chat.id, m.from_user.id):
        return replied_user, None

    return None, "Ответом на чужое сообщение зелёную строку может ставить или убирать только админ."

def ensure_manual_green_row(chat_id: int, sc: Sheets, user) -> int | None:
    uid = int(user.id)
    row = sc.find_row_by_uid(uid)
    if row is not None:
        return row

    if not AUTO_BIND_UID:
        return None

    rows = sc.rows()
    display_name = telegram_user_display_name(user)
    found_row = find_row_by_fio_in_rows(rows, display_name)
    if found_row is not None:
        sc.write(found_row, "J", uid)
        return found_row

    return sc.append_start_user(display_name, "", uid)

async def handle_manual_green_command(m: Message, text: str, msg_dt: datetime) -> bool:
    command = parse_manual_green_command(text, msg_dt.date())
    if command is None:
        return False

    if m.chat.id not in GROUPS or not m.from_user:
        return False

    target_user, error = resolve_manual_green_target(m)
    if error:
        await m.reply(error)
        return True
    if target_user is None:
        await m.reply("Не поняла, кому ставить зелёную строку.")
        return True

    remember_chat_user(m.chat.id, m.from_user)
    remember_chat_user(m.chat.id, target_user)

    chat_id = m.chat.id
    target_uid = int(target_user.id)
    target_name = html.escape(telegram_user_display_name(target_user))
    sc = get_sc(chat_id)
    row = ensure_manual_green_row(chat_id, sc, target_user)
    if row is None:
        await m.reply("Не нашла строку этого участника в таблице.")
        return True

    if command.action == "remove":
        remove_manual_green(chat_id, target_uid)
        remove_excused(chat_id, target_uid)
        sc.write(row, "I", "")
        sc.clear_row_background(row)
        await m.reply(f"Ок, убрала зелёную строку для <b>{target_name}</b> и очистила колонку I.")
        return True

    until_iso = command.until.isoformat() if command.until else ""
    set_manual_green(chat_id, target_uid, until_iso)
    sc.write(row, "I", command.sheet_value)
    sc.paint_row(row, GREEN)

    if command.until:
        await m.reply(
            f"Ок, поставила зелёную строку для <b>{target_name}</b> до <b>{command.sheet_value}</b>."
        )
    else:
        await m.reply(f"Ок, поставила зелёную строку для <b>{target_name}</b> без даты.")

    return True

def update_local_user_row(rows: list[list], row: int, uid: int, start_date: str = ""):
    row_index = row - 2
    if not 0 <= row_index < len(rows):
        return

    while len(rows[row_index]) <= 9:
        rows[row_index].append("")
    if start_date:
        while len(rows[row_index]) <= 8:
            rows[row_index].append("")
        rows[row_index][8] = start_date
    rows[row_index][9] = str(uid)

def append_local_user_row(rows: list[list], full_name: str, uid: int, start_date: str = ""):
    new_row = [""] * 11
    new_row[0] = full_name
    new_row[8] = start_date
    new_row[9] = str(uid)
    rows.append(new_row)

async def user_is_in_chat(chat_id: int, uid: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, uid)
    except (TelegramBadRequest, TelegramForbiddenError):
        return False

    status = getattr(member, "status", "")
    status_value = getattr(status, "value", str(status)).lower()
    if status_value in {"left", "kicked"}:
        return False
    if status_value == "restricted":
        return bool(getattr(member, "is_member", True))
    return True

def saved_user_sort_key(item) -> int:
    try:
        return int(normalize_uid_value(item[0]) or 0)
    except ValueError:
        return 0

async def sync_known_chat_users(chat_id: int, sc: Sheets, rows: list[list], existing_uids: set[str]) -> tuple[int, int, int, int]:
    added = 0
    linked_existing = 0
    skipped_no_name = 0
    skipped_not_in_chat = 0

    for uid_raw, info in sorted(get_users(chat_id).items(), key=saved_user_sort_key):
        uid_key = normalize_uid_value(uid_raw)
        if not uid_key or uid_key in existing_uids:
            continue

        try:
            uid = int(uid_key)
        except ValueError:
            continue

        if uid in ADMIN_IDS or is_admin(chat_id, uid):
            continue

        if not await user_is_in_chat(chat_id, uid):
            skipped_not_in_chat += 1
            continue

        full_name = saved_user_name(info)
        if not full_name:
            skipped_no_name += 1
            continue

        matched_row, matched_uid = find_row_by_candidate_name(rows, full_name)
        if matched_row is not None and not matched_uid:
            sc.write(matched_row, "J", uid)
            update_local_user_row(rows, matched_row, uid)
            linked_existing += 1
            existing_uids.add(uid_key)
            continue

        if matched_row is not None and matched_uid:
            continue

        sc.append_start_user(full_name, "", uid)
        append_local_user_row(rows, full_name, uid)
        added += 1
        existing_uids.add(uid_key)

    return added, linked_existing, skipped_no_name, skipped_not_in_chat

def _tsv_value(value) -> str:
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()

def start_candidate_history_path(chat_id: int, day: date) -> str:
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"start_candidates_{chat_id}_{day.isoformat()}.tsv")

def append_start_candidate_history(
    chat_id: int,
    uid: int,
    username: str | None,
    telegram_full_name: str | None,
    parsed_full_name: str,
    start_date: date,
    raw_text: str,
    msg_dt: datetime,
):
    path = start_candidate_history_path(chat_id, msg_dt.date())
    needs_header = not os.path.exists(path) or os.path.getsize(path) == 0
    sheet_date = start_date_sheet_value(start_date, today=msg_dt.date())

    with open(path, "a", encoding="utf-8", newline="") as f:
        if needs_header:
            f.write(
                "message_date\tchat_id\tuser_id\tusername\ttelegram_full_name\t"
                "parsed_full_name\tstart_date\tsheet_date\traw_text\n"
            )
        f.write(
            "\t".join(
                [
                    _tsv_value(msg_dt.isoformat()),
                    _tsv_value(chat_id),
                    _tsv_value(uid),
                    _tsv_value(username),
                    _tsv_value(telegram_full_name),
                    _tsv_value(parsed_full_name),
                    _tsv_value(start_date.isoformat()),
                    _tsv_value(sheet_date),
                    _tsv_value(raw_text),
                ]
            )
            + "\n"
        )

def build_start_candidate_history_from_state(chat_id: int, day: date) -> str | None:
    candidates = get_start_candidates(chat_id)
    rows = []
    for uid, candidate in candidates.items():
        if not isinstance(candidate, dict):
            continue
        message_date_raw = str(candidate.get("message_date", "")).strip()
        try:
            message_dt = datetime.fromisoformat(message_date_raw)
        except Exception:
            continue
        if message_dt.date() != day:
            continue
        rows.append((uid, candidate, message_dt))

    if not rows:
        return None

    path = start_candidate_history_path(chat_id, day)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(
            "message_date\tchat_id\tuser_id\tusername\ttelegram_full_name\t"
            "parsed_full_name\tstart_date\tsheet_date\traw_text\n"
        )
        for uid, candidate, message_dt in sorted(rows, key=lambda item: item[2]):
            try:
                start_date = date.fromisoformat(str(candidate.get("start_date", "")))
            except Exception:
                continue
            sheet_date = start_date_sheet_value(start_date, today=message_dt.date())
            f.write(
                "\t".join(
                    [
                        _tsv_value(message_dt.isoformat()),
                        _tsv_value(chat_id),
                        _tsv_value(uid),
                        "",
                        "",
                        _tsv_value(candidate.get("full_name", "")),
                        _tsv_value(start_date.isoformat()),
                        _tsv_value(sheet_date),
                        _tsv_value(candidate.get("raw_text", "")),
                    ]
                )
                + "\n"
            )

    return path

def parse_history_day(raw: str | None, base: date) -> date | None:
    if not raw:
        return base

    value = raw.strip()
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass

    match = re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", value)
    if not match:
        return None

    day = int(match.group(1))
    month = int(match.group(2))
    year_raw = match.group(3)
    year = base.year
    if year_raw:
        year = int(year_raw)
        if year < 100:
            year += 2000

    try:
        return date(year, month, day)
    except ValueError:
        return None

def remember_start_candidate(m: Message, text: str, msg_dt: datetime) -> bool:
    if m.chat.id not in GROUPS or not m.from_user or getattr(m.from_user, "is_bot", False):
        return False

    candidate = parse_start_candidate(text, base_date=msg_dt.date())
    if candidate is None:
        return False

    uid = m.from_user.id
    save_mention(m.chat.id, uid, mention_from_user(m.from_user))
    save_user(m.chat.id, uid, getattr(m.from_user, "username", None), getattr(m.from_user, "full_name", None))
    save_start_candidate(
        m.chat.id,
        uid,
        candidate.full_name,
        candidate.start_date.isoformat(),
        text,
        msg_dt.isoformat(),
    )
    append_start_candidate_history(
        m.chat.id,
        uid,
        getattr(m.from_user, "username", None),
        getattr(m.from_user, "full_name", None),
        candidate.full_name,
        candidate.start_date,
        text,
        msg_dt,
    )
    print(
        "START_CANDIDATE",
        "chat_id=", m.chat.id,
        "uid=", uid,
        "name=", candidate.full_name,
        "start_date=", candidate.start_date.isoformat(),
    )
    return True

@dp.message(Command("pingred"))
async def ping_red(m: Message):
    if not m.from_user:
        return

    if m.from_user.id not in ADMIN_IDS and not is_admin(m.chat.id, m.from_user.id):
        await m.reply("⛔️ У тебя нет доступа к этой команде.")
        return

    cleanup_expired_excused_until(m.chat.id)
    today = datetime.now(tz).date()
    cleanup_expired_manual_green(m.chat.id, today=today)
    manual_green = get_manual_green(m.chat.id)

    sc = get_sc(m.chat.id)
    red_uids = red_report_uids(
        sc.rows(),
        lambda uid: is_excused_today(m.chat.id, uid),
        lambda uid: manual_green_entry_is_active(manual_green.get(str(uid)), today),
    )

    if not red_uids:
        await m.answer("Красных полосочек сейчас не нашла ✅")
        return

    _excused, _active, mentions, _excused_until = get_sets(m.chat.id)
    users = get_users(m.chat.id)
    tags = [mention_for_uid(uid, mentions, users) for uid in red_uids]
    await m.answer("Красные полосочки в таблице, когда в строй?\n\n" + "\n".join(tags))

@dp.message(Command("scan", "screen", "скрин"))
async def scan_start_candidates(m: Message):
    if not m.from_user:
        return

    if m.chat.id not in GROUPS:
        await m.reply("Команду /scan запускаем в группе, которая привязана к таблице.")
        return

    if m.from_user.id not in ADMIN_IDS and not is_admin(m.chat.id, m.from_user.id):
        await m.reply("⛔️ У тебя нет доступа к этой команде.")
        return

    remember_chat_user(m.chat.id, m.from_user)

    replied = getattr(m, "reply_to_message", None)
    replied_parsed = False
    if replied is not None:
        if getattr(replied, "from_user", None):
            remember_chat_user(m.chat.id, replied.from_user)
        reply_text = get_msg_text(replied)
        reply_dt = replied.date.astimezone(tz) if replied.date else datetime.now(tz)
        replied_parsed = remember_start_candidate(replied, reply_text, reply_dt)

    candidates = get_start_candidates(m.chat.id)
    pending = {
        uid: candidate
        for uid, candidate in candidates.items()
        if isinstance(candidate, dict) and not candidate.get("imported_at")
    }
    reply_notes = []
    if not pending and replied is not None and not replied_parsed:
        reply_notes.append("Не смогла разобрать сообщение, на которое ты ответила. Нужны ФИО и дата старта.")

    now = datetime.now(tz)
    sc = get_sc(m.chat.id)
    rows = sc.rows()
    existing_uids = existing_uids_from_rows(rows)

    added = 0
    linked_existing = 0
    already_in_table = 0
    duplicate_names = 0
    invalid = 0

    for uid_raw, candidate in sorted(pending.items(), key=lambda item: item[1].get("message_date", "")):
        try:
            uid = int(uid_raw)
            start_date = date.fromisoformat(str(candidate.get("start_date", "")))
        except Exception:
            invalid += 1
            continue

        full_name = str(candidate.get("full_name", "")).strip()
        if not full_name:
            invalid += 1
            continue

        uid_key = normalize_uid_value(uid)
        if uid_key in existing_uids:
            already_in_table += 1
            mark_start_candidate_imported(m.chat.id, uid, now.isoformat())
            continue

        date_value = start_date_sheet_value(start_date, today=now.date())
        matched_row, matched_uid = find_row_by_candidate_name(rows, full_name)

        if matched_row is not None:
            if matched_uid:
                duplicate_names += 1
                mark_start_candidate_imported(m.chat.id, uid, now.isoformat())
                continue

            sc.write(matched_row, "J", uid)
            if date_value:
                sc.write(matched_row, "I", date_value)
            linked_existing += 1
            existing_uids.add(uid_key)
            update_local_user_row(rows, matched_row, uid, date_value)

            mark_start_candidate_imported(m.chat.id, uid, now.isoformat())
            continue

        sc.append_start_user(full_name, date_value, uid)
        added += 1
        existing_uids.add(uid_key)
        append_local_user_row(rows, full_name, uid, date_value)
        mark_start_candidate_imported(m.chat.id, uid, now.isoformat())

    known_added, known_linked, skipped_no_name, skipped_not_in_chat = await sync_known_chat_users(
        m.chat.id,
        sc,
        rows,
        existing_uids,
    )

    parts = ["Скан завершён."]
    parts.extend(reply_notes)
    if added or pending:
        parts.append(f"Добавлено новых строк по заявкам: {added}.")
    if known_added:
        parts.append(f"Добавлено новых строк по user_id: {known_added}.")
    total_linked = linked_existing + known_linked
    if total_linked:
        parts.append(f"Привязала user_id к уже существующим строкам: {total_linked}.")
    if already_in_table:
        parts.append(f"Уже были в таблице по user_id: {already_in_table}.")
    if duplicate_names:
        parts.append(f"Пропустила как уже существующие ФИО: {duplicate_names}.")
    if invalid:
        parts.append(f"Не смогла разобрать сохранённых заявок: {invalid}.")
    if skipped_no_name:
        parts.append(f"Пропустила сохранённых user_id без имени/username: {skipped_no_name}.")
    if skipped_not_in_chat:
        parts.append(f"Пропустила user_id, которых Telegram сейчас не видит в группе: {skipped_not_in_chat}.")
    if not any([added, known_added, total_linked, already_in_table, duplicate_names, invalid, skipped_no_name, skipped_not_in_chat]) and not reply_notes:
        parts.append("Новых заявок и новых user_id для таблицы не нашла.")
    parts.append("Колонку I заполняю только если старт позже завтрашнего дня.")

    await m.reply("\n".join(parts))

@dp.message(Command("scan_history", "scanlog"))
async def scan_history(m: Message):
    if not m.from_user:
        return

    parts = (m.text or "").split()
    today = datetime.now(tz).date()
    target_chat_id = m.chat.id
    date_arg = None

    if m.chat.type == "private":
        if len(parts) < 2:
            await m.reply("В личке укажи chat_id группы: <code>/scan_history -1001234567890</code>")
            return
        try:
            target_chat_id = int(parts[1].strip())
        except ValueError:
            await m.reply("Не смогла разобрать chat_id. Пример: <code>/scan_history -1001234567890</code>")
            return
        if len(parts) >= 3:
            date_arg = parts[2]
    elif len(parts) >= 2:
        date_arg = parts[1]

    if target_chat_id not in GROUPS:
        await m.reply("Не нашла такую группу в config.GROUPS.")
        return

    if m.from_user.id not in ADMIN_IDS and not is_admin(target_chat_id, m.from_user.id):
        await m.reply("⛔️ У тебя нет доступа к этой команде.")
        return

    target_day = parse_history_day(date_arg, today)
    if target_day is None:
        await m.reply("Не смогла разобрать дату. Можно так: <code>/scan_history -1001234567890 09.05</code>")
        return

    path = start_candidate_history_path(target_chat_id, target_day)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        path = build_start_candidate_history_from_state(target_chat_id, target_day)

    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        await m.reply(f"За {target_day.isoformat()} сохранённых заявок на старт пока нет.")
        return

    try:
        await bot.send_document(
            m.from_user.id,
            FSInputFile(path),
            caption=f"Заявки на старт за {target_day.isoformat()} для chat_id {target_chat_id}",
        )
    except TelegramForbiddenError:
        await m.reply("Я не могу написать тебе в личные сообщения. Сначала открой диалог с ботом и нажми /start.")
        return

    if m.chat.type == "private":
        await m.reply("Отправила файл сюда.")

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

MEAL_WORDS = {"завтрак", "обед", "ужин", "перекус"}

def extract_fio_prefix(text: str) -> str:
    """
    Берём начало сообщения до слова приёма пищи/служебных слов.
    Примеры:
      "Сунко Софья завтрак" -> "Сунко Софья"
      "Сунко завтрак" -> "Сунко"
      "Сунко перекус 1" -> "Сунко"
    """
    t = _norm(text)
    parts = t.split()
    if not parts:
        return ""

    fio_parts = []
    for p in parts:
        if p in MEAL_WORDS:
            break
        # часто "перекус 1" / "перекус 2"
        if p.isdigit():
            break
        fio_parts.append(p)
        # максимум 2 слова ФИО (фамилия + имя)
        if len(fio_parts) >= 2:
            break

    return " ".join(fio_parts).strip()

def find_row_by_fio_in_rows(rows: list[list], fio: str) -> int | None:
    """
    Ищем строку по колонке A (индекс 0) по фамилии/ФИО.
    Возвращаем номер строки в sheet (начиная с 2).
    """
    fio_n = _norm(fio)
    if not fio_n:
        return None

    fio_first = fio_n.split()[0]

    for i, r in enumerate(rows, start=2):
        a = _norm(r[0] if len(r) > 0 else "")
        if not a:
            continue
        a_first = a.split()[0]

        # матч по фамилии (первое слово)
        if a_first == fio_first:
            return i

        # или полное совпадение первых 1-2 слов
        if a == fio_n:
            return i

    return None


# -------------------------
# КНОПКИ
# -------------------------
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[
        KeyboardButton(text="📌 Правила питания"),
        KeyboardButton(text="📋 Меню"),
        KeyboardButton(text="📝 Правила оформления отчета")
    ]],
    resize_keyboard=True
)

MENU_INLINE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=str(i), callback_data=f"menu:{i}") for i in range(1, 8)],
    [
        InlineKeyboardButton(text="🥞 сырники", callback_data="menu:syrniki"),
        InlineKeyboardButton(text="🫓 лаваш", callback_data="menu:lavash"),
        InlineKeyboardButton(text="🍪 печенье", callback_data="menu:cookie"),
        # InlineKeyboardButton(text="🍇 виноград", callback_data="menu:grape"),
        # InlineKeyboardButton(text="🍌 банан", callback_data="menu:banana"),
        # InlineKeyboardButton(text="🥬 свекла", callback_data="menu:beet"),
    ],
])

MENU_FILES = {
    "1": "menu_1.jpg",
    "2": "menu_2.jpg",
    "3": "menu_3.jpg",
    "4": "menu_4.jpg",
    "5": "menu_5.jpg",
    "6": "menu_6.jpg",
    "7": "menu_7.jpg",
    "grape": "vinograd.jpeg",
    "banana": "banana.jpeg",
    "beet": "svekla.jpeg",
    "syrniki": "сырники.jpg",
    "lavash": "Лаваш.jpg",
    "cookie": "Печенье.jpg",
}

def find_asset(filename: str) -> str | None:
    path = os.path.join(ASSETS_DIR, filename)
    return path if os.path.exists(path) else None

# -------------------------
# /start + кнопки
# -------------------------
@dp.message(F.text == "/start")
async def start(m: Message):
    print("CHAT_ID =", m.chat.id)
    await m.answer("Ок, я на связи. Выбирай 👇", reply_markup=MAIN_KEYBOARD)

@dp.message(F.text == "📌 Правила питания")
async def rules(m: Message):
    await m.answer(
        "📌<b>Правила приёма пищи</b>\n"
        "• <b>Завтрак</b>🥞 — в первый час после пробуждения\n"
        "• <b>Первый перекус</b>🍎 — спустя 2–4 часа после завтрака (до 11:00)\n"
        "• <b>Обед</b>🍝 — до 14:00\n"
        "• <b>Второй перекус</b>🥛 — до 16:00\n"
        "• <b>Ужин</b> — до 20:00",
        reply_markup=MAIN_KEYBOARD
    )

@dp.message(F.text == "📋 Меню")
async def menu(m: Message):
    await m.answer("Выбери меню 👇", reply_markup=MENU_INLINE)

@dp.message(F.text == "📝 Правила оформления отчета")
async def report_rules(m: Message):
    await m.answer(
        "📌 <b>ПРАВИЛА ОТЧЁТОВ В ЧАТЕ</b>\n"
        "Пожалуйста, соблюдаем формат — бот работает автоматически 🤖\n"
        "Если формат нарушен, отметка может не засчитаться.\n"
        "\n"
        "📝 <b>ОБЩЕЕ ПРАВИЛО</b>\n"
        "➡️ Один приём пищи / вес = одно сообщение\n"
        "➡️ Не объединяем несколько приёмов пищи в одном тексте\n"
        "\n"
        "🍽 <b>КАК ПИСАТЬ ПРИЁМЫ ПИЩИ</b>\n"
        "Сообщение начинаем с Фамилия (можно с именем), дальше — приём пищи:\n"
        "Примеры:\n"
        "Сунко завтрак\n"
        "Сунко перекус 1\n"
        "Сунко обед\n"
        "Сунко перекус 2\n"
        "Сунко ужин\n"
        "\n"
        "⚠️ <b>В первый день желательно писать Фамилия Имя, чтобы бот привязал вас к таблице.</b>\n"
        "\n"
        "❌ <b>ЕСЛИ ПРИЁМА ПИЩИ НЕ БУДЕТ</b>\n"
        "Пишем “не будет” или “без”:\n"
        "Сунко обед не будет\n"
        "Сунко без ужина\n"
        "Сунко второго перекуса не будет\n"
        "\n"
        "➡️ В таблице ставится минус (-)\n"
        "\n"
        "⚖️ <b>ВЕС</b>\n"
        "Любое сообщение про вес пишем обязательно со словом “вес”, иначе бот его не обработает:\n"
        "Сунко вес 80.0\n"
        "\n"
        "➡️ Пишем только актуальный вес, разница будет просчитана автоматически\n"
        "\n"
        "🌿 <b>ЕСЛИ СЕГОДНЯ БЕЗ ОТЧЁТОВ</b>\n"
        "Сегодня без отчётов\n"
        "Уехала, без отчётов\n"
        "Уехала до 14 января\n"
        "\n"
        "➡️ В таблице строка будет зелёной",
        reply_markup=MAIN_KEYBOARD
    )

@dp.callback_query(F.data.startswith("menu:"))
async def menu_pick(cb: CallbackQuery):
    key = cb.data.split(":", 1)[1]
    fname = MENU_FILES.get(key)

    if not fname:
        await cb.answer("Меню не найдено", show_alert=True)
        return

    path = find_asset(fname)
    if not path:
        await cb.message.answer(f"Файл не найден: {fname}")
        await cb.answer()
        return

    await cb.message.answer_photo(
        FSInputFile(path),
        caption=f"📋 Меню: {key}",
        reply_markup=MAIN_KEYBOARD
    )
    await cb.answer()

# -------------------------
# Главный хендлер отчётов (текст + подписи к фото)
# -------------------------
@dp.message(F.new_chat_members)
async def new_chat_members(m: Message):
    if m.chat.id not in GROUPS:
        return

    for user in m.new_chat_members or []:
        remember_chat_user(m.chat.id, user)

@dp.message((F.text | F.caption))
async def report_handler(m: Message):
    if not m.from_user:
        return

    if m.chat.id == -1003637264298:
        print(
            "MSG",
            "chat_id=", m.chat.id,
            "uid=", m.from_user.id,
            "username=", getattr(m.from_user, "username", None),
            "name=", m.from_user.full_name,
            "text=", (m.text or m.caption or "")
        )

    text = get_msg_text(m)
    msg_dt = m.date.astimezone(tz) if m.date else datetime.now(tz)

    if m.chat.id not in GROUPS:
        print(
            "UNKNOWN_CHAT",
            "chat_id=", m.chat.id,
            "uid=", m.from_user.id,
            "username=", getattr(m.from_user, "username", None),
            "name=", m.from_user.full_name,
            "text=", text,
        )
        return

    if getattr(m.from_user, "is_bot", False):
        return

    remember_chat_user(m.chat.id, m.from_user)
    if await handle_manual_green_command(m, text, msg_dt):
        return

    remember_start_candidate(m, text, msg_dt)

    if needs_weight_value_warning(text):
        await m.reply("⚠️ Вес нужно писать с цифрой в этом же сообщении: <code>Сунко вес 80</code>.")
        return

    if needs_weight_keyword_warning(text):
        await m.reply("⚠️ Не забывай ключевое слово <b>вес</b>: <code>Сунко вес 80</code>.")
        return

    if not message_is_report(text):
        return

    uid = m.from_user.id
    hour, minute = msg_dt.hour, msg_dt.minute

    mention = mention_from_user(m.from_user)

    chat_id = m.chat.id
    sc = get_sc(chat_id)
    save_mention(chat_id, uid, mention)
    save_user(chat_id, uid, getattr(m.from_user, "username", None), getattr(m.from_user, "full_name", None))

    meal_marks = extract_meal_marks(text, hour=hour)

    if is_excuse(text):
        until_iso = parse_until_date(text)
        if until_iso:
            set_excused_until(chat_id, uid, until_iso)
            await m.reply(f"Ок, принял. До <b>{until_iso}</b> не буду ждать отчёты ✅")
        else:
            mark_excused(chat_id, uid)
            await m.reply("Ок, принял. Сегодня отмечу зелёным ✅")

        if not meal_marks and parse_weight_delta(text) is None and parse_explicit_weight(text) is None:
            return

    row = sc.find_row_by_uid(uid)

    if AUTO_BIND_UID and row is None:
        fio = extract_fio_prefix(text)
        rows = sc.rows()
        found_row = find_row_by_fio_in_rows(rows, fio)

        if found_row is not None:
            sc.write(found_row, "J", uid)
            row = found_row
        else:
            new_row = len(rows) + 2
            fio_to_write = fio if fio else (m.from_user.full_name or "Участник")
            sc.write(new_row, "A", fio_to_write)
            sc.write(new_row, "J", uid)
            row = new_row

    if row is None:
        print(f"UID not found in sheet: chat_id={chat_id}, uid={uid}, text={text!r}")
        return

    delta = parse_weight_delta(text)
    explicit_weight = parse_explicit_weight(text)
    weight_message = explicit_weight is not None or delta is not None
    sheet_name = GROUPS[chat_id]["SHEET_NAME"] if weight_message else None
    row_uid_raw = sc.get_cell(f"J{row}") if weight_message else None
    row_name = sc.get_cell(f"A{row}") if weight_message else None
    row_uid = normalize_uid_value(row_uid_raw) if weight_message else ""
    expected_uid = normalize_uid_value(uid) if weight_message else ""
    prev_raw = sc.get_cell(f"B{row}") if weight_message else None
    prev = parse_sheet_weight(prev_raw) if weight_message else None
    new_weight = None

    if weight_message:
        print(
            "ROW_DEBUG",
            "uid=", uid,
            "row=", row,
            "row_uid=", row_uid_raw,
            "row_name=", row_name,
        )

        if row_uid != expected_uid:
            print(
                "WEIGHT_WARN",
                "reason=", "row_uid_mismatch",
                "chat_id=", chat_id,
                "sheet_name=", sheet_name,
                "uid=", uid,
                "row=", row,
                "row_uid=", row_uid_raw,
                "row_name=", row_name,
                "text=", text,
            )
            return

    if explicit_weight is not None:
        new_weight = explicit_weight
        sc.write(row, "B", explicit_weight)

        if prev is not None:
            diff = round(explicit_weight - prev, 3)
            if abs(diff) <= 5:
                sc.write(row, "C", diff)
            else:
                sc.write(row, "C", "")
                print(
                    "WEIGHT_WARN",
                    "reason=", "explicit_diff_too_large",
                    "chat_id=", chat_id,
                    "sheet_name=", sheet_name,
                    "uid=", uid,
                    "row=", row,
                    "row_uid=", row_uid_raw,
                    "row_name=", row_name,
                    "prev=", prev,
                    "new=", explicit_weight,
                    "diff=", diff,
                    "text=", text,
                )

            if delta is not None and abs(diff - delta) > 0.05:
                print(
                    "WEIGHT_DELTA_MISMATCH",
                    "chat_id=", chat_id,
                    "sheet_name=", sheet_name,
                    "uid=", uid,
                    "row=", row,
                    "row_uid=", row_uid_raw,
                    "row_name=", row_name,
                    "text=", text,
                    "reported_delta=", delta,
                    "calculated_delta=", diff,
                    "prev=", prev_raw,
                )
        else:
            sc.write(row, "C", "")

        mark_active(chat_id, uid)

    elif delta is not None:
        if prev is None:
            print(
                "WEIGHT_WARN",
                "reason=", "missing_previous_weight",
                "chat_id=", chat_id,
                "sheet_name=", sheet_name,
                "uid=", uid,
                "row=", row,
                "row_uid=", row_uid_raw,
                "row_name=", row_name,
                "text=", text,
            )
        else:
            candidate_weight = round(prev + delta, 3)
            if not 30 <= candidate_weight <= 200:
                print(
                    "WEIGHT_WARN",
                    "reason=", "delta_new_weight_out_of_range",
                    "chat_id=", chat_id,
                    "sheet_name=", sheet_name,
                    "uid=", uid,
                    "row=", row,
                    "row_uid=", row_uid_raw,
                    "row_name=", row_name,
                    "prev=", prev,
                    "delta=", delta,
                    "new=", candidate_weight,
                    "text=", text,
                )
            elif abs(candidate_weight - prev) > 5:
                print(
                    "WEIGHT_WARN",
                    "reason=", "delta_diff_too_large",
                    "chat_id=", chat_id,
                    "sheet_name=", sheet_name,
                    "uid=", uid,
                    "row=", row,
                    "row_uid=", row_uid_raw,
                    "row_name=", row_name,
                    "prev=", prev,
                    "delta=", delta,
                    "new=", candidate_weight,
                    "text=", text,
                )
            else:
                new_weight = candidate_weight
                sc.write(row, "B", candidate_weight)
                sc.write(row, "C", delta)
                mark_active(chat_id, uid)

    if weight_message:
        print(
            "WEIGHT_DEBUG",
            "chat_id=", chat_id,
            "sheet_name=", sheet_name,
            "uid=", uid,
            "row=", row,
            "row_uid=", row_uid_raw,
            "row_name=", row_name,
            "text=", text,
            "prev_raw=", repr(prev_raw),
            "prev_parsed=", prev,
            "explicit_weight=", explicit_weight,
            "delta=", delta,
            "new_weight=", new_weight if delta is not None else explicit_weight,
        )

    seen_meals = set()
    for meal, mark in meal_marks:
        if meal not in MEAL_TO_COL or meal in seen_meals:
            continue

        seen_meals.add(meal)
        col = MEAL_TO_COL[meal]
        sc.write(row, col, mark)
        mark_active(chat_id, uid)

        if mark == "+":
            msg = late_message(meal, hour, minute)
            if msg:
                await m.reply(msg)
# Отчёт: красим и отправляем
# -------------------------
async def report(chat_id: int):
    today = datetime.now(tz).date()
    cleanup_expired_excused_until(chat_id)
    expired_manual_green_uids = cleanup_expired_manual_green(chat_id, today=today)

    sc = get_sc(chat_id)
    for uid in expired_manual_green_uids:
        row = sc.find_row_by_uid(uid)
        if row is not None:
            sc.write(row, "I", "")
            sc.clear_row_background(row)

    rows = sc.rows()
    manual_green = get_manual_green(chat_id)

    for row_num, r in enumerate(rows, start=2):
        status = report_row_status(
            r,
            lambda uid: is_excused_today(chat_id, uid),
            lambda uid: manual_green_entry_is_active(manual_green.get(str(uid)), today),
        )
        if status is None:
            continue

        if status.has_any_food:
            remove_excused(chat_id, status.uid)
        if status.force_green:
            value = manual_green_entry_sheet_value(manual_green.get(str(status.uid)))
            current_value = str(r[8]).strip() if len(r) > 8 else ""
            if current_value != value:
                sc.write(row_num, "I", value)
            sc.paint_row(row_num, GREEN)
            continue
        if status.is_excused:
            sc.paint_row(row_num, GREEN)
            continue
        if status.red_row:
            sc.paint_row(row_num,RED)
            continue
        for col in status.red_cells:
            sc.paint_cell(row_num, col, RED)

    pdf_path = sc.export_pdf()
    jpg_path = pdf_to_jpeg(pdf_path)

    await  bot.send_photo(
        chat_id,
        FSInputFile(jpg_path),
        caption = "Отчет за день"
    )
# -------------------------
# Пинг по обеду: только тем, у кого реально пусто
# -------------------------
async def scheduled_report(chat_id: int):
    try:
        print(f"Scheduled report started: chat_id={chat_id}")
        await report(chat_id)
        print(f"Scheduled report finished: chat_id={chat_id}")
    except Exception:
        print(f"Scheduled report failed: chat_id={chat_id}")
        traceback.print_exc()


async def lunch_ping(chat_id: int):
    today = datetime.now(tz).date()
    cleanup_expired_excused_until(chat_id)
    cleanup_expired_manual_green(chat_id, today=today)

    sc = get_sc(chat_id)
    rows = sc.rows()
    _excused, _active, mentions, _excused_until = get_sets(chat_id)
    manual_green = get_manual_green(chat_id)

    missing = []
    for i, r in enumerate(rows, start=2):
        if len(r) <= 9 or not str(r[9]).strip():
            continue

        uid_raw = normalize_uid_value(r[9])
        if not uid_raw:
            continue
        uid = int(uid_raw)
        if is_excused_today(chat_id, uid):
            continue
        if manual_green_entry_is_active(manual_green.get(str(uid)), today):
            continue

        # lunch = колонка F = индекс 5
        lunch_val = str(r[5]).strip() if len(r) > 5 else ""
        if lunch_val == "":
            missing.append(uid)

    if not missing:
        return

    tags = [mentions.get(str(uid), f'<a href="tg://user?id={uid}">участник</a>') for uid in missing]
    text = (
        "⚠️ <b>Не вижу отчёт по обеду</b>\n"
        "Пожалуйста, отправьте отчёт по обеду 👇\n\n" +
        "\n".join(tags)
    )
    await bot.send_message(chat_id, text)

# -------------------------
# Запуск
# -------------------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)

    scheduler = AsyncIOScheduler(timezone=tz)

    for index, (chat_id, _cfg) in enumerate(GROUPS.items()):
        # Пинг по обеду
        scheduler.add_job(
            lunch_ping, "cron",
            hour=14, minute=30,
            args=[chat_id],
            id=f"lunch_ping_{chat_id}",
            replace_existing=True
        )

        # Отчёт вечером
        report_hour, report_minute = staggered_daily_time(
            index,
            base_hour=REPORT_HOUR,
            base_minute=REPORT_MINUTE,
            step_minutes=REPORT_STAGGER_MINUTES,
        )
        scheduler.add_job(
            scheduled_report, "cron",
            hour=report_hour, minute=report_minute,
            args=[chat_id],
            id=f"daily_report_{chat_id}",
            replace_existing=True,
            misfire_grace_time=REPORT_MISFIRE_GRACE_SECONDS
        )

    scheduler.start()
    print("Scheduler started.")
    for job in scheduler.get_jobs():
        print("JOB:", job.id, "next:", job.next_run_time)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

