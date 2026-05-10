import os
import re
import ssl
import time
import uuid
import random
from urllib.parse import urlencode
from typing import Optional, List, Tuple

GREEN = {"red": 0.8, "green": 0.95, "blue": 0.8}
RED   = {"red": 0.95, "green": 0.8,  "blue": 0.8}


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_ACCOUNT_PATH = os.path.join(BASE_DIR, "service_account.json")

# Таблица A..K
RANGE_ROWS = "A2:K"
TOTAL_COLS = 11  # A..K
EXPORT_TOTAL_COLS = 9  # A..I, without internal UID/service columns
EXPORT_FIRST_COL = "A"
EXPORT_FIRST_ROW = 1
DEFAULT_EXPORT_SCALE = 4

# UID в J
UID_COL_LETTER = "J"
UID_INDEX = 9  # A=0 -> J=9
Credentials = None
build = None
HttpError = None


def _load_google_api():
    global Credentials, build, HttpError
    if Credentials is not None:
        return

    from google.oauth2.service_account import Credentials as GoogleCredentials
    from googleapiclient.discovery import build as google_build
    from googleapiclient.errors import HttpError as GoogleHttpError

    Credentials = GoogleCredentials
    build = google_build
    HttpError = GoogleHttpError


def normalize_uid_value(value) -> str:
    raw = str(value or "").strip().lstrip("'")
    if not raw:
        return ""

    if raw.isdigit():
        return raw

    try:
        numeric = float(raw.replace(",", "."))
    except ValueError:
        digits_only = "".join(ch for ch in raw if ch.isdigit())
        return digits_only

    if numeric.is_integer():
        return str(int(numeric))
    return raw


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _first_two_words(s: str) -> Tuple[str, str]:
    s = _norm(s)
    if not s:
        return "", ""
    parts = s.split()
    surname = parts[0] if len(parts) >= 1 else ""
    name = parts[1] if len(parts) >= 2 else ""
    return surname, name

def _sheet_ref(title: str) -> str:
    title = title or ""
    if re.search(r"[ \-\(\)\[\]\:\,\.]", title) or "'" in title:
        title = title.replace("'", "''")
        return f"'{title}'"
    return title

def _column_letter(index: int) -> str:
    if index < 1:
        raise ValueError("column index must be >= 1")

    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters

def _last_data_row(rows: list[list]) -> int:
    last_row = EXPORT_FIRST_ROW
    for row_num, row in enumerate(rows, start=2):
        if any(str(cell).strip() for cell in row[:TOTAL_COLS]):
            last_row = row_num
    return last_row

def export_range_for_rows(rows: list[list]) -> str:
    last_col = _column_letter(EXPORT_TOTAL_COLS)
    return f"{EXPORT_FIRST_COL}{EXPORT_FIRST_ROW}:{last_col}{_last_data_row(rows)}"

class Sheets:
    def __init__(self, spreadsheet_id: str, sheet_name: str, export_scale: int = DEFAULT_EXPORT_SCALE):
        _load_google_api()

        if not os.path.exists(SERVICE_ACCOUNT_PATH):
            raise FileNotFoundError(f"service_account.json not found at: {SERVICE_ACCOUNT_PATH}")

        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_PATH,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )

        self.sheets = build("sheets", "v4", credentials=creds)
        self.drive  = build("drive", "v3", credentials=creds)
        self.sid = spreadsheet_id
        self.sheet = sheet_name
        self.sheet_ref = _sheet_ref(sheet_name)
        self.export_scale = int(export_scale or DEFAULT_EXPORT_SCALE)

        self._rows_cache = None
        self._rows_cache_ts = 0.0
        self._rows_cache_ttl = 2.0

        meta_req = self.sheets.spreadsheets().get(spreadsheetId=self.sid)
        meta = self._exec(meta_req)
        self.sheet_id = None
        for sh in meta.get("sheets", []):
            props = sh.get("properties", {})
            if props.get("title") == self.sheet:
                self.sheet_id = props.get("sheetId")
                break
        if self.sheet_id is None:
            self.sheet_id = meta["sheets"][0]["properties"]["sheetId"]

    def _exec(self, request, retries: int = 8, base_sleep: float = 0.8):
        for attempt in range(retries):
            try:
                return request.execute()

            except HttpError as e:
                status = getattr(e.resp, "status", None)
                if status in (429, 500, 503):
                    sleep_s = min(base_sleep * (2 ** attempt) + random.random(), 60)
                    time.sleep(sleep_s)
                    continue
                raise

            except ssl.SSLError:
                sleep_s = min(base_sleep * (2 ** attempt) + random.random(), 30)
                time.sleep(sleep_s)
                continue

        raise RuntimeError("Google API request failed after retries")

    def _drop_cache(self):
        self._rows_cache = None
        self._rows_cache_ts = 0.0

    def rows(self):
        now = time.time()
        if self._rows_cache is not None and (now - self._rows_cache_ts) <= self._rows_cache_ttl:
            return self._rows_cache

        req = self.sheets.spreadsheets().values().get(
            spreadsheetId=self.sid,
            range=f"{self.sheet_ref}!{RANGE_ROWS}",
        )
        vals = self._exec(req).get("values", [])
        self._rows_cache = vals
        self._rows_cache_ts = now
        return vals

    def write(self, row: int, col: str, val):
        req = self.sheets.spreadsheets().values().update(
            spreadsheetId=self.sid,
            range=f"{self.sheet_ref}!{col}{row}",
            valueInputOption="RAW",
            body={"values": [[val]]},
        )
        self._exec(req)
        self._drop_cache()

    def get_cell(self, cell: str) -> str:
        req = self.sheets.spreadsheets().values().get(
            spreadsheetId=self.sid,
            range=f"{self.sheet_ref}!{cell}",
        )
        res = self._exec(req)
        vals = res.get("values", [])
        return vals[0][0] if vals and vals[0] else ""

    def _col_index(self, col_letter: str) -> int:
        return ord(col_letter.upper()) - ord("A")

    def paint_row(self, row: int, color: dict):
        req = self.sheets.spreadsheets().batchUpdate(
            spreadsheetId=self.sid,
            body={"requests": [{
                "repeatCell": {
                    "range": {
                        "sheetId": self.sheet_id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": 0,
                        "endColumnIndex": TOTAL_COLS,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": color}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }]}
        )
        self._exec(req)

    def paint_cell(self, row: int, col_letter: str, color: dict):
        c = self._col_index(col_letter)
        req = self.sheets.spreadsheets().batchUpdate(
            spreadsheetId=self.sid,
            body={"requests": [{
                "repeatCell": {
                    "range": {
                        "sheetId": self.sheet_id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": c,
                        "endColumnIndex": c + 1
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": color}},
                    "fields": "userEnteredFormat.backgroundColor"
                }
            }]}
        )
        self._exec(req)

    def export_pdf(self) -> str:
        import requests

        token = self.sheets._http.credentials.token
        params = {
            "format": "pdf",
            "portrait": "true",
            "fitw": "true",
            "scale": str(self.export_scale),
            "size": "7",
            "top_margin": "0.20",
            "bottom_margin": "0.20",
            "left_margin": "0.20",
            "right_margin": "0.20",
            "sheetnames": "false",
            "printtitle": "false",
            "pagenumbers": "false",
            "gridlines": "false",
            "fzr": "false",
            "gid": str(self.sheet_id),
            "range": export_range_for_rows(self.rows()),
        }
        url = f"https://docs.google.com/spreadsheets/d/{self.sid}/export?{urlencode(params)}"

        headers = {
            "Authorization": f"Bearer {token}"
        }

        r = requests.get(url, headers=headers)
        r.raise_for_status()

        out_dir = os.path.join(BASE_DIR, "out")
        os.makedirs(out_dir, exist_ok=True)
        pdf_path = os.path.join(out_dir, f"sheet_{uuid.uuid4().hex}.pdf")

        with open(pdf_path, "wb") as f:
            f.write(r.content)

        return pdf_path

    def find_row_by_uid(self, uid: int) -> Optional[int]:
        target_uid = normalize_uid_value(uid)
        if not target_uid:
            return None

        rows = self.rows()
        for idx, r in enumerate(rows, start=2):
            if len(r) <= UID_INDEX:
                continue
            if normalize_uid_value(r[UID_INDEX]) == target_uid:
                return idx
        return None

    def find_rows_by_surname(self, surname: str) -> List[int]:
        surname = _norm(surname)
        if not surname:
            return []

        rows = self.rows()
        found: List[int] = []

        for idx, r in enumerate(rows, start=2):
            a = _norm(str(r[0]) if len(r) > 0 else "")

            # новый формат: A == фамилия
            if a == surname:
                found.append(idx)
                continue

            # страховка на случай старых строк, где в A было "Фамилия Имя"
            if a.split(" ", 1)[0] == surname:
                found.append(idx)

        return found

    def find_row_by_surname_name(self, surname: str, name: str) -> Optional[int]:
        surname = _norm(surname)
        name = _norm(name)
        if not surname:
            return None
        rows = self.rows()
        for idx, r in enumerate(rows, start=2):
            a = str(r[0]).strip().lower()
            b = str(r[1]).strip().lower() if len(r) > 1 else ""
            if a == surname and (not name or b == name):
                return idx

        return None

    def set_uid(self, row: int, uid: int):
        self.write(row, UID_COL_LETTER, str(uid))

    def append_user(self, surname: str, name: str, uid: int) -> int:
        full_name = (surname or "").strip()
        if name:
            full_name = f"{full_name} {name.strip()}"

        # A..K (11 колонок)
        new_row = [""] * TOTAL_COLS
        new_row[0] = surname or ""  # A
        new_row[1] = name or ""  # B
        new_row[9] = str(uid)  # J

        req = self.sheets.spreadsheets().values().append(
            spreadsheetId=self.sid,
            range=f"{self.sheet_ref}!A:K",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [new_row]},
        )
        res = self._exec(req)
        self._drop_cache()

        updated_range = res.get("updates", {}).get("updatedRange", "")
        m = re.search(r"!(?:A)?(\d+):", updated_range)
        if m:
            return int(m.group(1))

        return len(self.rows()) + 1

    def append_start_user(self, full_name: str, start_date: str, uid: int) -> int:
        new_row = [""] * TOTAL_COLS
        new_row[0] = (full_name or "").strip()  # A
        new_row[8] = (start_date or "").strip()  # I
        new_row[9] = str(uid)  # J

        req = self.sheets.spreadsheets().values().append(
            spreadsheetId=self.sid,
            range=f"{self.sheet_ref}!A:K",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [new_row]},
        )
        res = self._exec(req)
        self._drop_cache()

        updated_range = res.get("updates", {}).get("updatedRange", "")
        m = re.search(r"!(?:A)?(\d+):", updated_range)
        if m:
            return int(m.group(1))

        return len(self.rows()) + 1

