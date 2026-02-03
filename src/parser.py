import re
from typing import Optional

# -------------------------
# Приёмы пищи → колонка
# -------------------------
MEAL_COL = {
    "breakfast": "D",
    "snack1": "E",
    "lunch": "F",
    "snack2": "G",
    "dinner": "H",
}

# -------------------------
# Слова
# -------------------------
EXCUSE_WORDS = [
    "без отчетов", "без отчётов", "без фото", "фото не будет",
    "уехал", "уехала", "заболел", "заболела", "болею"
]

SKIP_PHRASES = [
    "не будет",
    "без ",
    "пропуск",
    "пропущ",
    "пропускаю",
]

# -------------------------
# Утилиты
# -------------------------
def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def is_excuse(text: str) -> bool:
    t = normalize(text)
    return any(w in t for w in EXCUSE_WORDS)


def is_skip(text: str) -> bool:
    t = normalize(text)
    return any(p in t for p in SKIP_PHRASES)


# -------------------------
# Приём пищи
# -------------------------
def detect_meal(text: str, hour: int | None = None) -> Optional[str]:
    """
    Возвращает: breakfast | snack1 | lunch | snack2 | dinner
    """
    t = normalize(text)

    # Явные
    if "завтрак" in t:
        return "breakfast"
    if "обед" in t:
        return "lunch"
    if "ужин" in t:
        return "dinner"

    # Перекусы
    if "перекус" in t:
        if "2" in t or "втор" in t:
            return "snack2"
        if "1" in t or "перв" in t:
            return "snack1"

        # если цифры нет — решаем по времени
        if hour is not None:
            if hour < 13:
                return "snack1"
            return "snack2"

    return None


# -------------------------
# Поздние приёмы пищи
# -------------------------
def late_message(meal: str, hour: int, minute: int) -> Optional[str]:
    total = hour * 60 + minute

    if meal == "snack1" and total > 11 * 60:
        return "⚠️ Первый перекус — до 11:00."
    if meal == "lunch" and total > 14 * 60:
        return "⚠️ Обед — до 14:00."
    if meal == "snack2" and total > 16 * 60:
        return "⚠️ Второй перекус — до 16:00."

    return None


# -------------------------
# Разница веса
# -------------------------
def parse_weight_delta(text: str) -> Optional[float]:
    """
    Возвращает разницу веса в КГ
    +0.5
    -0.3
    плюс 300 (г)
    минус 50
    """

    t = normalize(text).replace(",", ".")

    m = re.search(r"(плюс|минус|\+|-)\s*(\d+(?:\.\d+)?)", t)
    if not m:
        return None

    sign = -1 if m.group(1) in ("-", "минус") else 1
    val = float(m.group(2))

    # граммы → кг
    if "гр" in t or "грам" in t or val >= 10:
        val = val / 1000

    delta = round(sign * val, 3)

    # защита от бреда
    if abs(delta) > 5:
        return None

    return delta


# -------------------------
# Абсолютный вес
# -------------------------
def parse_absolute_weight(text: str) -> Optional[float]:
    """
    Абсолютный вес:
    49
    49.5
    вес 49.2
    """

    t = normalize(text).replace(",", ".")

    # если есть признаки дельты — не абсолют
    if any(x in t for x in ["+", "-", "минус", "плюс", "гр", "грам"]):
        return None

    # если это еда — не вес
    if any(w in t for w in ["завтрак", "обед", "ужин", "перекус"]):
        return None

    m = re.search(r"\b(\d{2,3}(?:\.\d{1,3})?)\b", t)
    if not m:
        return None

    val = float(m.group(1))

    if 30 <= val <= 200:
        return round(val, 3)

    return None
