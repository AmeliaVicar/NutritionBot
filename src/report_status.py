from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from sheets import normalize_uid_value


MEAL_IDX = {
    "D": 3,
    "E": 4,
    "F": 5,
    "G": 6,
    "H": 7,
}

ALL_MEALS = ("D", "E", "F", "G", "H")
MAIN_MEALS = ("D", "F", "H")
MEAL_MARKS = {"+", "-"}


@dataclass(frozen=True)
class ReportRowStatus:
    uid: int
    has_any_food: bool
    is_excused: bool
    red_row: bool
    red_cells: tuple[str, ...]


def row_uid(row: Sequence[object]) -> Optional[int]:
    if len(row) <= 9 or not str(row[9]).strip():
        return None

    uid_raw = normalize_uid_value(row[9])
    if not uid_raw:
        return None

    try:
        return int(uid_raw)
    except ValueError:
        return None


def _cell_val(row: Sequence[object], letter: str) -> str:
    idx = MEAL_IDX[letter]
    return str(row[idx]).strip() if len(row) > idx else ""


def report_row_status(
    row: Sequence[object],
    is_excused_today: Callable[[int], bool],
) -> Optional[ReportRowStatus]:
    uid = row_uid(row)
    if uid is None:
        return None

    values = {col: _cell_val(row, col) for col in ALL_MEALS}
    has_any_food = any(value in MEAL_MARKS for value in values.values())
    is_excused = not has_any_food and is_excused_today(uid)
    red_row = not has_any_food and not is_excused
    red_cells = (
        tuple(col for col in MAIN_MEALS if values[col] == "")
        if has_any_food
        else ()
    )

    return ReportRowStatus(
        uid=uid,
        has_any_food=has_any_food,
        is_excused=is_excused,
        red_row=red_row,
        red_cells=red_cells,
    )


def red_report_uids(
    rows: Sequence[Sequence[object]],
    is_excused_today: Callable[[int], bool],
) -> list[int]:
    red_uids: list[int] = []
    seen: set[int] = set()

    for row in rows:
        status = report_row_status(row, is_excused_today)
        if status is None or status.uid in seen:
            continue
        if status.red_row or status.red_cells:
            red_uids.append(status.uid)
            seen.add(status.uid)

    return red_uids
