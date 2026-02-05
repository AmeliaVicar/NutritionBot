import asyncio
import os
import re
from datetime import datetime

import pytz
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
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
    parse_weight_delta,
    parse_absolute_weight,
)
from sheets import Sheets, GREEN, RED
from exporter import pdf_to_jpeg
from state import (
    mark_active, mark_excused, get_sets, save_mention,
    set_excused_until, is_excused_today, parse_until_date, cleanup_expired_excused_until
)

# -------------------------
# 0) Инициализация
# -------------------------
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

sc = Sheets(SPREADSHEET_ID, SHEET_NAME)
tz = pytz.timezone(TZ)

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
    """
    Чтобы не терять сообщения типа:
    "49.7" или "-0.3" или "минус 300"
    """
    t = (text or "").lower().replace(",", ".").strip()
    if not t:
        return False

    # если парсер уже видит — отлично
    if parse_weight_delta(t) is not None:
        return True
    if parse_absolute_weight(t) is not None:
        return True

    # запасной вариант: просто число 2-3 знака (49 / 49.7)
    if re.fullmatch(r"\d{2,3}(\.\d{1,3})?", t):
        return True

    return False

def message_is_report(text: str) -> bool:
    """
    Пропускаем:
    - еду
    - вес/разницу
    - "без отчётов"/отмазки
    """
    if not text or text.startswith("/"):
        return False

    t = text.lower()

    # отмазка
    if is_excuse(t):
        return True

    # еда
    if any(w in t for w in ["завтрак", "обед", "ужин", "перекус"]):
        return True

    # вес/дельта (в том числе "49.7" без слова "вес")
    if looks_like_weight_or_delta(text):
        return True

    return False

# /reportnow
@dp.message(F.text == "/reportnow")
async def report_now(m: Message):
    if not m.from_user:
        return

    # защита: чтобы не любой участник мог дергать отчёт
    if m.from_user.id not in ADMIN_IDS:
        await m.reply("⛔️ У тебя нет доступа к этой команде.")
        return

    await m.reply("⏳ Формирую отчёт...")
    await report()
    await m.reply("✅ Отчёт отправлен.")


# -------------------------
# КНОПКИ (тексты НЕ ТРОГАЮ)
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
        InlineKeyboardButton(text="🥞 сырники", callback_data="menu:сырники"),
        InlineKeyboardButton(text="🫓 лаваш", callback_data="menu:лаваш"),
        InlineKeyboardButton(text="🍪 печенье", callback_data="menu:печенье"),
        InlineKeyboardButton(text="🍇 виноград", callback_data="menu:виноград"),
        InlineKeyboardButton(text="🍌 банан", callback_data="menu:банан"),
        InlineKeyboardButton(text="🥬 свекла", callback_data="menu:свекла"),
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
    "виноград": "vinograd.jpeg",
    "банан": "banana.jpeg",
    "свекла": "svekla.jpeg",
    "сырники": "сырники.jpg",
    "лаваш": "Лаваш.jpg",
    "печенье": "Печенье.jpg",
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
        "Если пишете разницу от вчера:\n"
        "Сунко -1.35\n"
        "Сунко минус 300\n"
        "Сунко плюс 200\n"
        "\n"
        "Если первый/абсолютный вес — обязательно со словами “первый вес”:\n"
        "Сунко первый вес 80.0\n"
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

    text = get_msg_text(m)
    if not message_is_report(text):
        return

    uid = m.from_user.id
    now = datetime.now(tz)
    hour, minute = now.hour, now.minute

    # mentions для пингов
    if m.from_user.username:
        mention = "@" + m.from_user.username
    else:
        safe_name = (m.from_user.full_name or "участник").replace("<", "").replace(">", "")
        mention = f'<a href="tg://user?id={uid}">{safe_name}</a>'
    save_mention(uid, mention)

    # EXCUSE
    if is_excuse(text):
        until_iso = parse_until_date(text)
        if until_iso:
            set_excused_until(uid, until_iso)
            await m.reply(f"Ок, принял. До <b>{until_iso}</b> не буду ждать отчёты ✅")
        else:
            mark_excused(uid)
            await m.reply("Ок, принял. Сегодня отмечу зелёным ✅")
        return

    # строка по UID
    row = sc.find_row_by_uid(uid)
    if row is None:
        return

    # -------- ВЕС --------
    delta = parse_weight_delta(text)
    abs_w = parse_absolute_weight(text)

    # Абсолютный
    if abs_w is not None:
        prev_raw = sc.get_cell(f"B{row}")
        sc.write(row, "B", abs_w)

        try:
            prev = float(str(prev_raw).replace(",", "."))
            diff = round(abs_w - prev, 3)
            if abs(diff) <= 5:
                sc.write(row, "C", diff)
            else:
                sc.write(row, "C", "")
        except Exception:
            sc.write(row, "C", "")

        mark_active(uid)

    # Дельта
    elif delta is not None:
        prev_raw = sc.get_cell(f"B{row}")
        try:
            prev = float(str(prev_raw).replace(",", "."))
        except Exception:
            # нет прошлого веса — не пытаемся “считать из воздуха”
            return

        new_weight = round(prev + delta, 3)
        if not (30 <= new_weight <= 200):
            return

        sc.write(row, "B", new_weight)
        sc.write(row, "C", delta)
        mark_active(uid)

    # -------- ЕДА --------
    meal = detect_meal(text, hour=hour)
    if meal and meal in MEAL_TO_COL:
        col = MEAL_TO_COL[meal]
        skipped = is_skip(text)
        mark = "-" if skipped else "+"
        sc.write(row, col, mark)
        mark_active(uid)

        # late ping только если это "+"
        if not skipped:
            msg = late_message(meal, hour, minute)
            if msg:
                await m.reply(msg)

# -------------------------
# Отчёт: красим и отправляем
# -------------------------
async def report():
    cleanup_expired_excused_until()
    _excused, _active, _mentions, _excused_until = get_sets()
    rows = sc.rows()

    # Индексы колонок (A=0)
    MEAL_IDX = {
        "D": 3,  # завтрак
        "E": 4,  # перекус 1
        "F": 5,  # обед
        "G": 6,  # перекус 2
        "H": 7,  # ужин
    }

    ALL_MEALS = ["D", "E", "F", "G", "H"]
    MAIN_MEALS = ["D", "F", "H"]  # завтрак / обед / ужин

    for row_num, r in enumerate(rows, start=2):
        # UID в J
        if len(r) <= 9 or not str(r[9]).strip():
            continue

        uid = int(str(r[9]).strip())

        def cell_val(letter: str) -> str:
            idx = MEAL_IDX[letter]
            return str(r[idx]).strip() if len(r) > idx else ""

        # 🟢 1. Если предупредил — зелёная строка
        if is_excused_today(uid):
            sc.paint_row(row_num, GREEN)
            continue

        values = {col: cell_val(col) for col in ALL_MEALS}
        has_any_food = any(v != "" for v in values.values())

        # 🔴 2. Если ВООБЩЕ НИЧЕГО НЕТ
        if not has_any_food:
            sc.paint_row(row_num, RED)
            continue

        # 🔴 3. Если что-то было — проверяем ТОЛЬКО основные приёмы
        for col in MAIN_MEALS:
            if values[col] == "":
                sc.paint_cell(row_num, col, RED)

    # Отправка отчёта
    jpg_path = pdf_to_jpeg(sc.export_pdf())
    await bot.send_photo(
        TELEGRAM_CHAT_ID,
        FSInputFile(jpg_path),
        caption="Отчёт за день"
    )

# -------------------------
# Пинг по обеду: только тем, у кого реально пусто
# -------------------------
async def lunch_ping():
    cleanup_expired_excused_until()
    rows = sc.rows()
    _excused, _active, mentions, _excused_until = get_sets()

    missing = []
    for i, r in enumerate(rows, start=2):
        if len(r) <= 9 or not str(r[9]).strip():
            continue

        uid = int(str(r[9]).strip())
        if is_excused_today(uid):
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
    await bot.send_message(TELEGRAM_CHAT_ID, text)

# -------------------------
# Reset: в 21:50 (как ты просила)
# -------------------------
async def daily_reset():


# -------------------------
# Запуск
# -------------------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)

    scheduler = AsyncIOScheduler(timezone=tz)

    # Пинг по обеду (как у тебя было)
    scheduler.add_job(
        lunch_ping, "cron",
        hour=14, minute=30,
        id="lunch_ping",
        replace_existing=True
    )

    # Отчёт вечером
    scheduler.add_job(
        report, "cron",
        hour=20, minute=0,
        id="daily_report",
        replace_existing=True
    )

    scheduler.start()
    print("Scheduler started.")
    print("Next lunch ping:", scheduler.get_job("lunch_ping").next_run_time)
    print("Next report:", scheduler.get_job("daily_report").next_run_time)
   

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

