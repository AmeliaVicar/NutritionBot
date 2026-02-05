import os
import re
import ssl
import time
import uuid
import random
from typing import Optional, List, Tuple

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

GREEN = {"red": 0.8, "green": 0.95, "blue": 0.8}
RED   = {"red": 0.95, "green": 0.8,  "blue": 0.8}


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_ACCOUNT_PATH = os.path.join(BASE_DIR, "service_account.json")

# Таблица A..K
RANGE_ROWS = "A2:K"
TOTAL_COLS = 11  # A..K

# UID в J
UID_COL_LETTER = "J"
UID_INDEX = 9  # A=0 -> J=9

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

class Sheets:
    def __init__(self, spreadsheet_id: str, sheet_name: str):
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

        url = (
            f"https://docs.google.com/spreadsheets/d/{self.sid}/export"
            f"?format=pdf"
            f"&portrait=false"
            f"&fitw=true"
            f"&scale=2"
            f"&sheetnames=false"
            f"&printtitle=false"
            f"&pagenumbers=false"
            f"&gridlines=false"
            f"&fzr=false"
            f"&gid={self.sheet_id}"
        )

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
        rows = self.rows()
        for idx, r in enumerate(rows, start=2):
            if len(r) > UID_INDEX and str(r[UID_INDEX]).strip() == str(uid):
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

