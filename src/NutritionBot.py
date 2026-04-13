import asyncio
import os
import re
import traceback
from datetime import datetime

import pytz
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery,
    FSInputFile,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import *
from parser import (
    detect_meal,
    is_skip,
    is_excuse,
    late_message,
    looks_like_meal_report,
    looks_like_weight_report,
    extract_meal_marks,
    parse_explicit_weight,
    parse_sheet_weight,
    parse_weight_delta,
)
from sheets import Sheets, GREEN, RED, normalize_uid_value
from exporter import pdf_to_jpeg
from schedule_utils import staggered_daily_time
from state import (
    mark_active, mark_excused, get_sets, save_mention, save_user, get_users,
    set_excused_until, is_excused_today, parse_until_date, cleanup_expired_excused_until, remove_excused
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
        _sheets_cache[chat_id] = Sheets(cfg["SPREADSHEET_ID"], cfg["SHEET_NAME"])
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

PING_RED_TEXT = """
<a href="tg://user?id=5279334155">Алтухова Марина</a>
<a href="tg://user?id=2100715616">Арзуманян Лиана</a>
<a href="tg://user?id=5115459415">Бабаян Гаяна</a>
<a href="tg://user?id=1669980170">Бадрудинова Оксана</a>
<a href="tg://user?id=649538125">Белоусова Анастасия</a>
<a href="tg://user?id=5185585128">Бервенюк Оля</a>
<a href="tg://user?id=765179844">Бугрова Олеся</a>
<a href="tg://user?id=7893797472">Гусакова Екатерина</a>
<a href="tg://user?id=5656786633">Ива Елена</a>
<a href="tg://user?id=8381043498">Карасова Наталья</a>
<a href="tg://user?id=861439342">Крапивка Анастасия</a>
<a href="tg://user?id=1715220925">Миронова Марина</a>
<a href="tg://user?id=619951300">Новак Мария</a>
<a href="tg://user?id=6434567306">Омарова Гюрибика</a>
<a href="tg://user?id=1313349421">Печёнова Алёна</a>
<a href="tg://user?id=1753865678">Побединская Ирина</a>
<a href="tg://user?id=6773392466">Полиновская Олеся</a>
<a href="tg://user?id=1093571023">Пучешкина Лимана</a>
<a href="tg://user?id=8098434798">Романчук Яна</a>
<a href="tg://user?id=666696400">Саркисова Марина</a>
<a href="tg://user?id=2049751335">Суровцева Анна</a>
<a href="tg://user?id=1155392295">Урих Алёна</a>
<a href="tg://user?id=5304427052">Федюкина Наталья</a>
<a href="tg://user?id=941749370">Христинченко Екатерина</a>
<a href="tg://user?id=2022633639">Черемисина Мария</a>

Когда в строй?
""".strip()

@dp.message(Command("pingred"))
async def ping_red(m: Message):
    if not m.from_user:
        return

    if m.from_user.id not in ADMIN_IDS and not is_admin(m.chat.id, m.from_user.id):
        await m.reply("⛔️ У тебя нет доступа к этой команде.")
        return

    await m.answer(PING_RED_TEXT)

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
        InlineKeyboardButton(text="🍇 виноград", callback_data="menu:grape"),
        InlineKeyboardButton(text="🍌 банан", callback_data="menu:banana"),
        InlineKeyboardButton(text="🥬 свекла", callback_data="menu:beet"),
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
        "Сунко вес минус 300\n"
        "Сунко вес плюс 200\n"
        "Сунко вес -1,000\n"
        "Сунко вес +0,400\n"
        "\n"
        "➡️ Абсолютный вес: Сунко вес 80.0\n"
        "➡️ Разница от вчера: Сунко вес минус 300\n"
        "➡️ Если вес без изменений: Сунко вес тот же\n"
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
    if not message_is_report(text):
        return

    uid = m.from_user.id
    msg_dt = m.date.astimezone(tz) if m.date else datetime.now(tz)
    hour, minute = msg_dt.hour, msg_dt.minute

    if m.from_user.username:
        mention = "@" + m.from_user.username
    else:
        safe_name = (m.from_user.full_name or "участник").replace("<", "").replace(">", "")
        mention = f'<a href="tg://user?id={uid}">{safe_name}</a>'

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
    cleanup_expired_excused_until(chat_id)

    sc = get_sc(chat_id)
    rows = sc.rows()

    _excused, _active, _mentions, _excused_until = get_sets(chat_id)

    MEAL_IDX = {
        "D": 3,
        "E": 4,
        "F": 5,
        "G": 6,
        "H": 7,
    }

    ALL_MEALS = ["D", "E", "F", "G", "H"]
    MAIN_MEALS = ["D", "F", "H"]

    for row_num, r in enumerate(rows, start=2):
        if len(r) <= 9 or not str(r[9]).strip():
            continue

        uid_raw = normalize_uid_value(r[9])
        if not uid_raw:
            continue
        uid = int(uid_raw)

        def cell_val(letter: str) -> str:
            idx = MEAL_IDX[letter]
            return str(r[idx]).strip() if len(r) > idx else ""

        values = {col: cell_val(col) for col in ALL_MEALS}

        has_any_food = any(v in {"+", "-"} for v in values.values())
        if has_any_food:
            remove_excused(chat_id, uid)
        if is_excused_today(chat_id, uid):
            sc.paint_row(row_num, GREEN)
            continue
        if not has_any_food:
            sc.paint_row(row_num,RED)
            continue
        for col in MAIN_MEALS:
            if values[col] == "":
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
    cleanup_expired_excused_until(chat_id)

    sc = get_sc(chat_id)
    rows = sc.rows()
    _excused, _active, mentions, _excused_until = get_sets(chat_id)

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

