"""Explicit Russian date grammar. Never let a language model invent a date."""
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

MONTHS = {name: i + 1 for i, name in enumerate((
    "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
    "сентября", "октября", "ноября", "декабря"))}
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}(?:[./]\d{4})?|\d{1,2}\s+(?:" + "|".join(MONTHS) + r")(?:\s+\d{4})?)\b", re.I)
TIME_RE = re.compile(r"\b(?:(?:в|с)\s*)?([01]?\d|2[0-3]):([0-5]\d)\b")


def date_parts(text, tz="Asia/Almaty", now=None):
    """Return only observed fields; absent/invalid/ambiguous fields stay absent."""
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(tz)).date()
    lower = text.lower().replace("ё", "е")
    result = {"date": None, "time": None, "date_quote": None, "time_quote": None, "error": None}
    match = DATE_RE.search(lower)
    if match:
        raw = match.group()
        result["date_quote"] = text[match.start():match.end()]
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                value = datetime.strptime(raw, "%Y-%m-%d").date()
            elif re.search(r"[./]", raw):
                parts = re.split(r"[./]", raw)
                value = today.replace(year=int(parts[2]) if len(parts) == 3 else today.year, month=int(parts[1]), day=int(parts[0]))
            else:
                parts = raw.split()
                value = today.replace(year=int(parts[2]) if len(parts) == 3 else today.year, month=MONTHS[parts[1]], day=int(parts[0]))
            result["date"] = value.isoformat()
        except ValueError:
            result["error"] = "Такой даты нет. Укажите существующий день, месяц и год."
    else:
        relative = re.search(r"\b(послезавтра|завтра|сегодня)\b", lower)
        if relative:
            days = {"сегодня": 0, "завтра": 1, "послезавтра": 2}[relative.group()]
            result.update(date=(today + timedelta(days=days)).isoformat(), date_quote=relative.group())
    match = TIME_RE.search(lower)
    if match:
        result.update(time=f"{int(match[1]):02}:{match[2]}", time_quote=text[match.start():match.end()])
    else:
        match = re.search(r"\bв\s+(\d{1,2})(?:\s*(утра|дня|вечера|ночи|часов?))?\b(?![:\d])", lower)
        if match:
            hour = int(match[1])
            period = match[2]
            if period in {"дня", "вечера"} and 1 <= hour < 12:
                hour += 12
            elif period == "ночи" and hour == 12:
                hour = 0
            if 0 <= hour <= 23 and (period or hour == 0 or hour >= 12):
                result.update(time=f"{hour:02}:00", time_quote=match.group())
            else:
                result["error"] = "Уточните время в 24-часовом формате, например 13:00."
    if re.search(r"\b\d{1,2}:\d{2}\b", lower) and not result["time"]:
        result["error"] = "Укажите время от 00:00 до 23:59."
    return result


def aware_wall(date, clock, tz):
    zone = ZoneInfo(tz)
    naive = datetime.fromisoformat(f"{date}T{clock}")
    value = naive.replace(tzinfo=zone)
    if value.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != naive:
        raise ValueError("Это местное время не существует из-за перевода часов")
    if value.utcoffset() != value.replace(fold=1).utcoffset():
        raise ValueError("Это время неоднозначно из-за перевода часов. Выберите другое время")
    return value
