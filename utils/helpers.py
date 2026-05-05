from datetime import date, datetime
import pytz


def normalize_phone(phone: str) -> str:
    phone = str(phone).strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone


def today_ist() -> str:
    return datetime.now(pytz.timezone("Asia/Kolkata")).date().isoformat()


def now_ist() -> str:
    return datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")


def weeks_until(date_str: str) -> int:
    try:
        target = date.fromisoformat(str(date_str))
        return max(0, (target - date.today()).days // 7)
    except Exception:
        return 0
