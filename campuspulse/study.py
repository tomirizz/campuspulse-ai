"""Auditable custom tools. All calculations, retrieval and checks run in code."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from campuspulse.dates import date_parts, aware_wall
from campuspulse.models import Preferences
from campuspulse.planner import plan_week
from campuspulse.progress import proof


def source_lines(materials):
    for material in materials:
        for page in material["pages"]:
            for line_no, line in enumerate(page["text"].splitlines(), 1):
                if not line.strip():
                    continue
                # Preserve exact substrings even for PDFs with extremely long lines.
                for offset in range(0, len(line), 1000):
                    quote = line[offset:offset + 1000]
                    yield {"material_id": material["id"], "file": material["name"], "page": page["page"],
                           "line": line_no, "start": offset, "quote": quote,
                           "why": proof("Точная цитата", "substring(извлечённая строка, начало, длина)",
                           {"страница": page["page"], "строка": line_no, "символы": [offset + 1, offset + len(quote)]},
                           quote, material["name"], "Номера строк относятся к извлечённому тексту PDF, не к его вёрстке.")}


def validate_source(materials, source):
    match = next((s for s in source_lines(materials) if all(s[k] == source.get(k) for k in ("material_id", "page", "line", "start", "quote"))), None)
    if not match:
        raise ValueError("Источник изменился или недоступен. Повторно откройте материал")
    return match


STOP = {"что", "как", "это", "для", "или", "мой", "мои", "по", "из", "на", "в", "об", "о", "и", "с", "а", "the", "of", "and", "найди", "покажи", "материал", "лекци", "говорится", "сравни", "во", "всех", "файлах"}


def terms(text):
    # A documented prefix heuristic, not a semantic similarity or confidence score.
    return {w[:6] for w in re.findall(r"[\w]+", text.lower().replace("ё", "е")) if len(w) > 1 and w[:6] not in STOP and w not in STOP}


def search_materials(materials, query, limit=12):
    wanted = terms(query)
    ranked = []
    for source in source_lines(materials):
        overlap = wanted & terms(source["quote"])
        if overlap:
            source["matched_terms"] = sorted(overlap)
            source["score"] = len(overlap)
            ranked.append(source)
    ranked.sort(key=lambda s: (-s["score"], s["file"], s["page"], s["line"], s["start"]))
    matches = ranked[:limit]
    differences = []
    for i, a in enumerate(matches):
        for b in matches[i + 1:]:
            na, nb = re.findall(r"\d+(?:[.,]\d+)?", a["quote"]), re.findall(r"\d+(?:[.,]\d+)?", b["quote"])
            shared = (terms(a["quote"]) & terms(b["quote"])) - wanted
            if a["material_id"] != b["material_id"] and na and nb and na != nb and len(shared) >= 2:
                differences.append({"a": a, "b": b, "note": "В похожих фрагментах разные числа. Это повод сверить контекст, а не установленное противоречие."})
    return {"query": query, "matches": matches, "possible_differences": differences[:4], "total_matches": len(ranked),
            "why": proof("Почему найдены эти фрагменты", "score = число общих префиксов слов длиной до 6 символов; сортировка по убыванию score",
            {"запрос": query, "слова": sorted(wanted), "лимит": limit}, len(matches), "Текущие загруженные материалы → study.search_materials",
            "Это поиск по словам, не оценка истинности. Отсутствие совпадения не доказывает отсутствие ответа; переформулируйте запрос.")}


def syllabus_candidates(material, preferences=None, now=None):
    prefs = preferences or {}
    candidates, grading = [], []
    for source in source_lines([material]):
        text = source["quote"]
        if re.search(r"(?:оцен|вес|финал|экзамен|midterm|final|grade|weight).*\d+\s*%", text, re.I):
            grading.append(source)
        if not re.search(r"лаборатор|задани|сдать|дедлайн|deadline|assignment|project|проект|эссе|контрольн|экзамен", text, re.I):
            continue
        parts = date_parts(text, prefs.get("timezone", "Asia/Almaty"), now)
        due = None
        if parts["date"] and parts["time"] and not parts["error"]:
            due = aware_wall(parts["date"], parts["time"], prefs.get("timezone", "Asia/Almaty")).isoformat()
        candidates.append({"id": hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()[:24],
                           "title": text.strip()[:160], "course": "", "due_at": due, "date": parts["date"], "time": parts["time"],
                           "estimated_minutes": None, "source": source, "why": source["why"],
                           "missing": [name for name, value in (("курс", None), ("дата", parts["date"]), ("время", parts["time"]), ("оценка длительности", None)) if value is None],
                           "note": parts["error"] or "Проверьте название и срок. Курс и длительность задаёте вы; задачи пока не сохранены."})
    return {"material_id": material["id"], "candidates": candidates[:30], "grading_rules": grading[:15],
            "why": proof("Как разобран силлабус", "строки с маркерами заданий → явные дата и время → предложение для проверки",
            {"файл": material["name"], "найдено": len(candidates), "лимит": 30}, len(candidates[:30]), "study.syllabus_candidates",
            "Таблицы, относительные недели и сложная вёрстка требуют ручной проверки. Даты и веса из отсутствующего текста не создаются.")}


def scenario(tasks, preferences, changes, now=None):
    now = now or datetime.now(timezone.utc)
    allowed = {"daily_minutes", "start_hour", "end_hour", "busy", "delay_days", "days"}
    if set(changes) - allowed:
        raise ValueError("Неизвестное изменение сценария")
    delay, days = changes.get("delay_days", 0), changes.get("days", 7)
    if not isinstance(delay, int) or not 0 <= delay <= 13 or not isinstance(days, int) or not 1 <= days <= 14:
        raise ValueError("Горизонт — 1–14 дней; отложить начало можно на 0–13 дней")
    updated = {**preferences, **{k: v for k, v in changes.items() if k not in {"delay_days", "days"}}}
    if delay:
        updated["busy"] = [*updated.get("busy", []), {"start": now.isoformat(), "end": (now + timedelta(days=delay)).isoformat()}]
    updated = Preferences.model_validate(updated).model_dump(mode="json")
    before, after = plan_week(tasks, preferences, now, days), plan_week(tasks, updated, now, days)
    changes_by_task = []
    for task in tasks:
        old = [{k: s[k] for k in ("start", "end", "minutes")} for s in before["sessions"] if s["task_id"] == task["id"]]
        new = [{k: s[k] for k in ("start", "end", "minutes")} for s in after["sessions"] if s["task_id"] == task["id"]]
        if old != new:
            changes_by_task.append({"task_id": task["id"], "title": task["title"], "before": old, "after": new})
    delta = after["scheduled_minutes"] - before["scheduled_minutes"]
    return {"before": before, "after": after, "changes": changes_by_task, "preferences": updated, "delta_minutes": delta,
            "why": proof("Почему изменился план", "Δ минут = новый план − исходный план; одинаковые задачи, часы сервера и алгоритм",
            {"изменения": changes, "исходные минуты": before["scheduled_minutes"], "новые минуты": after["scheduled_minutes"]}, delta,
            "study.scenario → planner.plan_week", "Это предпросмотр. Сохранённые настройки не меняются автоматически.")}


def scenario_from_message(message, preferences=None, now=None):
    """Only explicit user quantities can become scenario parameters."""
    lower = message.lower()
    for word, number in {"один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14}.items():
        lower = re.sub(r"\b" + word + r"\b", str(number), lower)
    changes = {}
    if re.search(r"сегодня\s+(?:я\s+)?(?:не успеваю|не могу|занят|занята)", lower):
        prefs = preferences or {}
        now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(prefs.get("timezone", "Asia/Almaty")))
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        changes["busy"] = [*prefs.get("busy", []), {"start": now.isoformat(), "end": midnight.isoformat()}]
    daily = re.search(r"(\d{1,3})\s*(час\w*|минут\w*)\s+в\s+день", lower)
    if daily:
        changes["daily_minutes"] = int(daily[1]) * (60 if daily[2].startswith("час") else 1)
    delay = re.search(r"(?:начну|начать|отложить)\s+(?:через|на)\s+(\d{1,2})\s+д", lower)
    if delay:
        changes["delay_days"] = int(delay[1])
    days = re.search(r"(?:осталось|на ближайшие|за)\s+(\d{1,2})\s+д", lower)
    if days:
        changes["days"] = int(days[1])
    return changes


def grade_target(config):
    components = config["components"]
    if not 2 <= len(components) <= 20:
        raise ValueError("Нужно от 2 до 20 компонентов оценки")
    target = Decimal(str(config["target"]))
    if not target.is_finite() or not 0 <= target <= 100:
        raise ValueError("Целевая оценка должна быть от 0 до 100")
    total_weight, earned, missing = Decimal(0), Decimal(0), []
    parts = []
    for item in components:
        weight, maximum = Decimal(str(item["weight"])), Decimal(str(item["max_score"]))
        if not weight.is_finite() or not maximum.is_finite() or not 0 < weight <= 100 or maximum <= 0:
            raise ValueError("Вес должен быть больше 0 и не больше 100%; максимум баллов — больше 0")
        total_weight += weight
        if item["score"] is None:
            missing.append((weight, maximum, item["name"]))
            continue
        score = Decimal(str(item["score"]))
        if not score.is_finite() or not 0 <= score <= maximum:
            raise ValueError("Набранный балл должен быть от 0 до максимума компонента")
        contribution = weight * score / maximum
        earned += contribution
        parts.append({"name": item["name"], "contribution": str(contribution), "score": str(score), "max_score": str(maximum), "weight": str(weight)})
    if total_weight != 100 or len(missing) != 1:
        raise ValueError("Сумма весов должна быть ровно 100%; оставьте ровно один неизвестный балл")
    weight, maximum, name = missing[0]
    raw = (target - earned) * maximum / weight
    required = max(Decimal(0), raw).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    achievable = raw <= maximum
    return {"target": str(target), "earned_contribution": str(earned.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "required_score": str(required), "max_score": str(maximum), "component": name,
            "achievable": achievable, "already_reached": raw <= 0,
            "maximum_final": str((earned + weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)), "contributions": parts,
            "why": proof("Откуда взят нужный балл", "вклад = вес% × балл / максимум; нужный балл = max(0, (цель − сумма вкладов) × максимум финала / вес финала)",
            config, str(required), "Введённая вами система оценивания → study.grade_target",
            "Decimal; нужный балл округляется вверх до 0,01. Формула применима к взвешенной сумме без дополнительных порогов/штрафов. Веса должен подтвердить пользователь.")}


def quest_candidates(material):
    items = []
    for source in source_lines([material]):
        if re.search(r"сдать|дедлайн|deadline|\b\d+\s*%", source["quote"], re.I):
            continue
        match = re.fullmatch(r"\s*([^:—=\n]{2,70})\s*[:—=]\s*(.{3,240})\s*", source["quote"])
        if not match:
            continue
        answer, description = match[1].strip(), match[2].strip()
        if not re.search(r"[А-Яа-яA-Za-z]", answer):
            continue
        identity = hashlib.sha256((answer.casefold() + "\n" + description.casefold()).encode()).hexdigest()
        if any(q["id"] == identity for q in items):
            continue
        items.append({"id": identity, "question": "Восстановите термин из материала: «_____ — " + description + "»", "answer": answer, "source": source,
                      "why": source["why"]})
    return {"questions": items[:20], "why": proof("Как созданы квесты", "строка «термин: определение» → скрыть термин; эталон = точный термин из той же строки",
            {"файл": material["name"]}, len(items[:20]), "study.quest_candidates", "Проверьте эталоны перед запуском. Это воспроизведение материала, а не оценка понимания всей темы.")}


def normalize_answer(text):
    return " ".join(text.casefold().replace("ё", "е").split()).strip(". ")


def diagnose(code, language="python", filename="snippet.py"):
    if not code.strip() or len(code) > 60000:
        raise ValueError("Вставьте код длиной от 1 до 60 000 символов")
    if language not in {"python", "json"}:
        raise ValueError("Проверка поддерживает Python и JSON")
    issues = []
    try:
        if language == "python":
            compile(code, filename, "exec", dont_inherit=True)
        else:
            # Python accepts these extensions; JSON does not. Skip quoted strings.
            for token in re.finditer(r'"(?:\\.|[^"\\])*"|(?P<nonfinite>-?\b(?:NaN|Infinity)\b)', code):
                if token.group("nonfinite"):
                    raise json.JSONDecodeError("Non-finite numbers are not valid JSON", code, token.start())
            json.loads(code)
    except (SyntaxError, json.JSONDecodeError) as exc:
        line = exc.lineno or 1
        column = (exc.offset if isinstance(exc, SyntaxError) else exc.colno) or 1
        quote = code.splitlines()[line - 1] if line <= len(code.splitlines()) else ""
        message = exc.msg
        hint = "Синтаксический анализатор остановился в указанной позиции. Проверьте конструкцию на этой строке и незакрытые скобки выше."
        for pattern, explanation in [("expected ':'", "В указанной позиции ожидается двоеточие."), ("was never closed", "Открытая скобка не была закрыта; проверьте соответствующую пару."), ("unexpected indent", "Отступ появился там, где анализатор его не ожидает."), ("expected an indented block", "После начала блока ожидается строка с отступом."), ("outside function", "Этот оператор допускается только внутри функции."), ("Expecting property name", "Имя поля JSON должно быть строкой в двойных кавычках."), ("Expecting value", "В указанной позиции JSON ожидает значение."), ("Extra data", "После первого JSON-значения найдены дополнительные данные.")]:
            if pattern in message:
                hint = explanation
                break
        issues.append({"line": line, "column": column, "message": message, "quote": quote,
                       "hint": hint,
                       "why": proof("Источник диагностики", "сообщение штатного синтаксического анализатора без изменения ИИ",
                       {"файл": filename, "строка": line, "столбец": column, "код": quote}, message,
                       "Python compile (без исполнения)" if language == "python" else "Python json.loads + проверка запрета NaN/Infinity в JSON")})
    except (RecursionError, ValueError, MemoryError):
        raise ValueError("Фрагмент слишком сложный для проверки. Разделите его на части")
    return {"filename": filename, "language": language, "issues": issues, "syntax_ok": not issues,
            "why": proof("Что проверено", "синтаксический разбор текста; код не исполняется",
            {"файл": filename, "язык": language, "sha256": hashlib.sha256(code.encode()).hexdigest()},
            "Синтаксическая ошибка" if issues else "Синтаксических ошибок не найдено", "study.diagnose",
            "Успех синтаксического разбора не доказывает правильность алгоритма, безопасность или прохождение тестов.")}
