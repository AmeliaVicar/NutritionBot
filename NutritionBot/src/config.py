import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Sheet1")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
TZ = os.getenv("TZ", "Europe/Moscow")
EXPORT_SCALE = int(os.getenv("EXPORT_SCALE", "2"))
ADMIN_IDS = {830570573}
