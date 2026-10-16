"""Versioned game rules. Pure functions: no model, random rewards or hidden scores."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

RULE_VERSION = "progress-v1"


def proof(title, formula, inputs, result, source, note=""):
    return {"title": title, "formula": formula, "inputs": inputs, "result": result,
            "source": source, "note": note, "version": RULE_VERSION}


def reward(minutes):
    return 20 + min(40, 5 * ((minutes + 29) // 30))


def complete_task(task, completed, now=None):
    task = dict(task)
    task["completed"] = completed
    if completed and "reward_snapshot" not in task:
        task["reward_snapshot"] = {"minutes": task["estimated_minutes"],
                                   "xp": reward(task["estimated_minutes"]), "rule": RULE_VERSION}
        task["completed_at"] = (now or datetime.now(timezone.utc)).isoformat()
    return task


def task_proof(task):
    snap = task.get("reward_snapshot") or {"minutes": task["estimated_minutes"], "xp": reward(task["estimated_minutes"])}
    return proof("Опыт за задание", "XP = 20 + min(40, 5 × ceil(оценка минут / 30))",
                 {"задание": task["title"], "task_id": task["id"], "оценка минут": snap["minutes"], "завершено": task.get("completed", False)},
                 snap["xp"], "Ваше задание → estimated_minutes; campuspulse/progress.py → reward",
                 "Это игровые баллы за самостоятельную отметку выполнения, не оценка знаний. Оценка времени фиксируется при первом завершении. Возврат в работу убирает XP; повторное завершение возвращает прежний XP. Удаление задания убирает его XP.")


def progress(tasks, preferences=None, now=None, quest_rewards=None):
    tz = ZoneInfo((preferences or {}).get("timezone", "Asia/Almaty"))
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    done = [t for t in tasks if t.get("completed")]
    # Legacy completions have no invented completion dates and no retroactive rewards.
    credited = [t for t in done if t.get("reward_snapshot") and t.get("completed_at")]
    quest_rewards = quest_rewards or []
    total = sum(t["reward_snapshot"]["xp"] for t in credited) + sum(q["xp"] for q in quest_rewards)
    dates = {datetime.fromisoformat(t["completed_at"]).astimezone(tz).date() for t in credited}
    today = now.date()
    cursor = today if today in dates else today - timedelta(days=1)
    streak = 0
    while cursor in dates:
        streak += 1
        cursor -= timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    weekly = [t for t in credited if week_start <= datetime.fromisoformat(t["completed_at"]).astimezone(tz).date() <= today]
    daily = [t for t in credited if datetime.fromisoformat(t["completed_at"]).astimezone(tz).date() == today]
    earned = len(credited)
    evidence = {
        "xp": proof("Общий опыт", "XP = сумма XP завершённых заданий + 10 × число уникальных освоенных фактов", {"задания": [{"название": t["title"], "id": t["id"], "XP": t["reward_snapshot"]["xp"]} for t in credited], "квесты": [{"id": q["id"], "XP": q["xp"]} for q in quest_rewards]}, total,
                    "Задания → completed, reward_snapshot; campuspulse/progress.py → progress", "Повторные отметки не суммируются. Баллы не измеряют успеваемость."),
        "level": proof("Уровень", "уровень = 1 + floor(XP / 100); прогресс = XP mod 100", {"XP": total}, 1 + total // 100,
                       "Правило progress-v1: порог уровня 100 XP"),
        "streak": proof("Серия дней", "число последовательных дат с завершением, заканчивающихся сегодня или вчера", {"даты": sorted(str(d) for d in dates), "сегодня": str(today), "часовой пояс": str(tz)}, streak,
                        "Серверное время первого завершения → completed_at", "За пропуск нет штрафов и списания опыта."),
        "weekly": proof("Цель недели", "прогресс = min(завершено с понедельника / 3, 1) × 100%", {"понедельник": str(week_start), "задания": [t["id"] for t in weekly]}, len(weekly),
                        "Серверные даты завершения; цель 3 задания — фиксированное правило продукта"),
    }
    badges = []
    for target, name, mark in [(1, "Первый шаг", "✦"), (3, "В ритме", "↗"), (5, "Исследователь", "◎"), (10, "Навигатор", "✺"), (20, "Мастер маршрута", "◇")]:
        badges.append({"id": f"done-{target}", "name": name, "mark": mark, "target": target, "current": earned,
                       "unlocked": earned >= target, "why": proof(name, "получено, если завершённых заданий ≥ порога",
                       {"завершено": earned, "порог": target}, earned >= target, "Задания с сохранённой наградой → completed, reward_snapshot")})
    return {"xp": total, "level": 1 + total // 100, "level_progress": total % 100, "next_level_xp": 100 - total % 100,
            "streak": streak, "completed": earned, "weekly_completed": len(weekly), "weekly_target": 3,
            "weekly_percent": min(100, len(weekly) * 100 // 3), "daily_completed": len(daily),
            "badges": badges, "why": evidence, "rule_version": RULE_VERSION,
            "ledger": [{"task_id": t["id"], "title": t["title"], "xp": t["reward_snapshot"]["xp"],
                        "at": t["completed_at"], "why": task_proof(t)} for t in sorted(credited, key=lambda t: t["completed_at"], reverse=True)] +
                       [{"task_id": q["id"], **q} for q in quest_rewards]}


def metrics(tasks, now=None):
    now = now or datetime.now(timezone.utc)
    opened = [t for t in tasks if not t.get("completed")]
    soon = [t for t in opened if now <= datetime.fromisoformat(t["due_at"]) <= now + timedelta(hours=48)]
    minutes = sum(t["estimated_minutes"] for t in opened)
    return {"open": len(opened), "due": len(soon), "minutes": minutes, "hours": round(minutes / 60, 1),
            "why": {
                "open": proof("В работе", "count(задания, где completed = false)", {"task_ids": [t["id"] for t in opened]}, len(opened), "Ваши сохранённые задания"),
                "due": proof("Ближайшие дедлайны", "count(открытые задания, где сейчас ≤ дедлайн ≤ сейчас + 48 часов)", {"сейчас": now.isoformat(), "дедлайны": [t["due_at"] for t in soon]}, len(soon), "Ваши due_at + часы сервера", "Просроченные задания сюда не входят."),
                "hours": proof("Учебная нагрузка", "часы = round(сумма оценок минут / 60, 1)", {t["id"]: t["estimated_minutes"] for t in opened}, round(minutes / 60, 1), "Ваши estimated_minutes", "Это ваша оценка времени, не прогноз ИИ.")}}
