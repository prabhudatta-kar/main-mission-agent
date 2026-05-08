import os
from dotenv import load_dotenv

load_dotenv()

WATI_API_URL = os.getenv("WATI_API_URL")
WATI_API_TOKEN = os.getenv("WATI_API_TOKEN")
WATI_API_KEY = os.getenv("WATI_API_KEY")    # separate key for template management

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

GOOGLE_SHEETS_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")
GOOGLE_SHEETS_WORKBOOK_ID = os.getenv("GOOGLE_SHEETS_WORKBOOK_ID")

FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON", "")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "").strip()

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")

WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "")

APP_ENV = os.getenv("APP_ENV", "development")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
MORNING_MESSAGE_HOUR = int(os.getenv("MORNING_MESSAGE_HOUR", 6))
EVENING_CHECKIN_HOUR = int(os.getenv("EVENING_CHECKIN_HOUR", 19))
DIGEST_HOUR = int(os.getenv("DIGEST_HOUR", 21))
