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
from parser import *
from sheets import Sheets, GREEN, RED

from exporter import pdf_to_jpeg

from state import (
    mark_active, mark_excused, get_sets, reset_day, save_mention,
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
# Таблица
# -------------------------
MEAL_TO_COL = {
    "breakfast": "D",
    "snack1": "E",
    "lunch": "F",
    "snack2": "G",
    "dinner": "H",
}


MEAL_WORDS = {
    "завтрак", "обед", "ужин",
    "перекус", "перекус1", "перекус2",
    "перекус 1", "перекус 2"
}

# -------------------------
# Утилиты
# -------------------------
def get_msg_text(m: Message) -> str:
    return (m.text or m.caption or "").strip()

def _clean_word(w: str) -> str:
    w = (w or "").strip().lower()
    w = re.sub(r"^[^\wа-яё]+", "", w)
    w = re.sub(r"[^\wа-яё]+$", "", w)
    return w

def extract_surname_and_optional_name(text: str) -> tuple[str, str]:
    parts = re.sub(r"\s+", " ", text.strip()).split(" ")
    surname = _clean_word(parts[0]) if parts else ""
    name = _clean_word(parts[1]) if len(parts) > 1 else ""
    if name in MEAL_WORDS:
        name = ""
    return surname, name

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
# КОМАНДЫ / КНОПКИ
# -------------------------
@dp.message(F.text == "/start")
async def start(m: Message):
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
    files = MENU_FILES.get(key)

    if not files:
        await cb.answer("Меню не найдено", show_alert=True)
        return

    if isinstance(files, str):
        files = [files]

    for fname in files:
        path = find_asset(fname)
        if not path:
            await cb.message.answer(f"Файл не найден: {fname}")
            continue

        await cb.message.answer_photo(
            FSInputFile(path),
            caption=f"📋 Меню: {key}",
            reply_markup=MAIN_KEYBOARD
        )

    await cb.answer()


# -------------------------
# ОТЧЁТНЫЙ HANDLER
# -------------------------
def message_is_report(text: str) -> bool:
    if not text or text.startswith("/"):
        return False
    return any(w in text.lower() for w in [
        "завтрак", "обед", "ужин",
        "перекус", "вес", "минус", "плюс", "не будет", "без"
    ])


@dp.message(
    (F.text | F.caption)
    & F.func(lambda m: message_is_report(get_msg_text(m)))
)
async def report_handler(m: Message):
    if not m.from_user:
        return

    uid = m.from_user.id
    text = get_msg_text(m)
    print("TEXT:", repr(text), "HAS_PHOTO:", bool(getattr(m, "photo", None)), "CAPTION:", repr(m.caption))


    # ищем строку пользователя
    row = sc.find_row_by_uid(uid)
    if row is None:
        return  # пока без автодобавления

    # -------- ВЕС --------
    delta = parse_weight_delta(text)
    abs_w = parse_absolute_weight(text)

    # 1️⃣ Абсолютный вес
    if abs_w is not None:
        prev_raw = sc.get_cell(f"B{row}")
        sc.write(row, "B", abs_w)

        try:
            prev = float(prev_raw)
            diff = round(abs_w - prev, 3)

            # защита от бреда
            if abs(diff) <= 5:
                sc.write(row, "C", diff)
            else:
                sc.write(row, "C", "")
        except:
            sc.write(row, "C", "")

    # 2️⃣ Разница веса
    elif delta is not None:
        prev_raw = sc.get_cell(f"B{row}")

        try:
            prev = float(prev_raw)
        except:
            return  # ❌ если нет старого веса — НИЧЕГО не делаем

        new_weight = round(prev + delta, 3)

        # 🔒 финальная защита
        if not (30 <= new_weight <= 200):
            return

        sc.write(row, "B", new_weight)
        sc.write(row, "C", delta)

    # -------- ЕДА --------
    meal = detect_meal(text)
    if meal and meal in MEAL_TO_COL:
        col = MEAL_TO_COL[meal]
        mark = "-" if is_skip(text) else "+"
        sc.write(row, col, mark)


# -------------------------
# ПИНГ ПО ОБЕДУ (ИСПРАВЛЕН)
# -------------------------
async def lunch_ping():
    cleanup_expired_excused_until()
    rows = sc.rows()
    _, _, mentions, _ = get_sets()

    missing = []
    for i, r in enumerate(rows, start=2):
        if len(r) < 10 or not r[9]:
            continue
        uid = int(r[9])
        if is_excused_today(uid):
            continue
        lunch = str(r[5]).strip()
        if lunch == "":
            missing.append(uid)

    if not missing:
        return

    text = "⚠️ <b>Не вижу отчёт по обеду</b>\n\n" + "\n".join(
        mentions.get(str(uid), f'<a href="tg://user?id={uid}">участник</a>')
        for uid in missing
    )
    await bot.send_message(TELEGRAM_CHAT_ID, text)

# -------------------------
# ЗАПУСК
# -------------------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(lunch_ping, "cron", hour=12, minute=30)
    scheduler.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


