import re
from typing import Optional

MEAL_COL = {
    "breakfast": "D",
    "snack1": "E",
    "lunch": "F",
    "snack2": "G",
    "dinner": "H",
}

SKIP_WORDS = ["не будет", "нет", "пропуск", "пропущ", "минус"]

EXCUSE_WORDS = [
    "без отчётов", "без отчетов", "без фото", "фото не будет",
    "уехал", "уехала", "заболел", "заболела", "болею"
]

def normalize(t):
    return t.lower().strip()

def is_excuse(text):
    t = normalize(text)
    return any(w in t for w in EXCUSE_WORDS)

def is_skip(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in [
        "без ", "не будет", "не буду", "пропуск", "пропущу", "пропущен", "пропускаю", "минус", "не"
    ])

def parse_meal(text: str) -> Optional[str]:
    t = (text or "").lower()

    # нормализация
    t = t.replace("перекус1", "перекус 1").replace("перекус2", "перекус 2")

    if "завтрак" in t:
        return "breakfast"
    if "обед" in t:
        return "lunch"
    if "ужин" in t:
        return "dinner"

    # перекусы
    if "перекус 1" in t or ("перекус" in t and "1" in t):
        return "snack1"
    if "перекус 2" in t or ("перекус" in t and "2" in t):
        return "snack2"
    if "перекус" in t:
        # если номер не указан — считаем как snack1 (или поменяй на None)
        return "snack1"

    return None


def late_message(meal: str, hour: int, minute: int) -> str | None:
    # Перекус 1 — до 11:00 (после 11:00:00 уже поздно)
    if meal == "snack1" and (hour > 11 or (hour == 11 and minute > 0)):
        return "⚠️ Перекус 1 — до 11:00."

    # Обед — до 14:00
    if meal == "lunch" and (hour > 14 or (hour == 14 and minute > 0)):
        return "⚠️ Обед — до 14:00."

    # Перекус 2 — до 16:00
    if meal == "snack2" and (hour > 16 or (hour == 16 and minute > 0)):
        return "⚠️ Перекус 2 — до 16:00."

    return None


def parse_weight_delta(text: str) -> Optional[float]:
    """
    Возвращает РАЗНИЦУ ВЕСА в кг (float) или None.
    Поддержка:
    +0.5
    -0.05
    плюс 300
    минус 50
    """

    t = (text or "").lower().replace(",", ".")

    # граммы считаем ТОЛЬКО если явно указаны
    is_grams = any(x in t for x in [" гр", "гр ", "грам", "г "])

    m = re.search(
        r"(?:^|\s)(плюс|минус|\+|-)\s*(\d+(?:\.\d+)?)(?:\s|$)",
        t
    )
    if not m:
        return None

    sign_word = m.group(1)
    sign = -1 if sign_word in ("-", "минус") else 1
    val = float(m.group(2))

    # граммы → кг
    if is_grams or val >= 10:
        val = val / 1000

    val = round(sign * val, 3)

    # 🔒 финальный стоп-кран
    if abs(val) > 5:
        return None

    return val



def parse_absolute_weight(text: str) -> Optional[float]:
    """
    Абсолютный вес в кг или None.
    Поддержка: "Фамилия 49.5", "Фамилия вес 49.5"
    Диапазон: 30–200
    """

    t = (text or "").lower().replace(",", ".").strip()
    if not t:
        return None

    # если это похоже на дельту — не трогаем
    if any(x in t for x in ["+", "-", "минус", "плюс", "гр", "грам", " g", "г "]):
        return None

    # если это сообщение про еду — не путать с весом
    if any(w in t for w in ["завтрак", "обед", "ужин", "перекус"]):
        return None

    # берём первое число, но аккуратно
    m = re.search(r"\b(\d{2,3}(?:\.\d{1,3})?)\b", t)
    if not m:
        return None

    val = float(m.group(1))

    if 30 <= val <= 200:
        return round(val, 3)

    return None





