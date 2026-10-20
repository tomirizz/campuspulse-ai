"""Conservative, deterministic extraction of grading rules and dated schedules.

Only observed weights are returned. Local attestation points are converted to
course percentages only when an explicit outer formula is present.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from fractions import Fraction
import re
from zoneinfo import ZoneInfo


EXAMPLE_SYLLABUS_TEXT = """EXAMPLE — supplied High Performance Computing syllabus excerpt
Course title: High Performance Computing (HPC)
Number of credits: 5
1st attestation
Assignments: 40
assignment 1: 40
Mid Term: 60
2nd attestation
Assignments: 40
assignment 2: 20
assignment 3: 20
End Term: 60
Final exam: Quiz 100
Total: 0.3 * 1st Att + 0.3 * 2nd Att + 0.4 * Final
"""

MAX_TEXT = 150_000
_NUMBER = r"\d+(?:[.,]\d+)?"
_FIRST = r"(?:1\s*(?:-?\s*(?:st|ая|я|й))?\s*(?:attestation|att\b|аттестаци\w*|рубежн\w*\s+контрол\w*)|(?:attestation|att|аттестаци\w*|рк)\s*1|перв\w*\s+аттестаци\w*)"
_SECOND = r"(?:2\s*(?:-?\s*(?:nd|ая|я|й))?\s*(?:attestation|att\b|аттестаци\w*|рубежн\w*\s+контрол\w*)|(?:attestation|att|аттестаци\w*|рк)\s*2|втор\w*\s+аттестаци\w*)"
_FINAL = r"(?:final(?:\s+exam)?|финал\w*(?:\s+экзамен)?|итогов\w*\s+экзамен)"
_ASSIGNMENT = r"(?:assignment|ассайнмент|задани[ея]|проект|project|quiz|квиз|lab(?:oratory)?|лабораторн\w*)"
_MID = r"(?:mid\s*[- ]?\s*term|мид\s*терм|мидтерм)"
_END = r"(?:end\s*[- ]?\s*term|енд\s*терм|эндтерм|энд\s*терм)"
_COMPONENT = re.compile(rf"(?:{_ASSIGNMENT}\s*\d*|{_MID}|{_END}|{_FINAL})", re.I)
_TIME_RANGE = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\s*[-—–]\s*([01]?\d|2[0-3])[:.]([0-5]\d)\b")


def _plain_markup(text):
    """Read simple Markdown/LaTeX formatting, never evaluate its contents."""
    value = text.replace("\\times", "*").replace("\\cdot", "*")
    value = re.sub(r"\\text\{([^{}]*)\}", lambda m: m[1].replace("\\ ", " "), value)
    return value.replace("\\(", "").replace("\\)", "").replace("**", "").replace("__", "").replace("\\ ", " ").strip()


def _named_point_row(line):
    """Read a complete named points row without knowing assessment vocabulary."""
    value = re.sub(r"^(?:[-*•]\s+|\d+[.)]\s+)", "", line.strip()).strip(" |")
    row = re.fullmatch(rf"(?P<title>.+?)\s*(?:[—:|=-]\s*)?(?P<points>{_NUMBER})\s*(?:points?|балл(?:а|ов)?)\s*[.;]?", value, re.I)
    if not row:
        return None
    title = re.sub(r"\s*\([^)]*\)\s*$", "", row["title"].strip(" :|=-—"))
    # Policy prose and totals are not assessments even when they end in points.
    if (not title or len(title) > 160 or not re.search(r"[A-Za-zА-Яа-яЁё]", title)
            or re.match(r"(?:total|subtotal|weight|max(?:imum)?|late\s+submissions?|automatic\s+fail|missing\s+a\s+deadline|итог|подытог|вес|максимум|правил)\b", title, re.I)):
        return None
    points = _float(row["points"])
    if not 0 < points <= 100000:
        return None
    return {"name": title, "points": points}


def _complete_weights(components):
    return abs(sum((Fraction(str(row["weight"])) for row in components), Fraction(0)) - 100) <= Fraction(1, 1000000)


def _policy_or_total_row(line):
    label = re.sub(r"^\s*(?:[-*•]\s+|#+\s*)", "", line).strip()
    return bool(re.match(r"(?:total|subtotal|weight|final\s*grade|overall\s*grade|grading\s*scale|policy|policies|automatic\s*fail|passing\s*(?:grade|score|mark)|minimum\s*(?:grade|score|mark)|итог|подытог|вес|правил|минимальн\w*\s+балл)\b", label, re.I)
                or re.search(r"\bless\s+than\b|\bat\s+least\b|\bmust\s+(?:score|obtain)\b|\bif\b.*\b(?:fail|below|score)\b|менее\s+\d|ниже\s+\d", label, re.I))


def _global_point_scheme(text):
    """Read explicit attestation maxima instead of assuming 100 local points.

    Example: Max30 points (30% final), works18+12. These already contribute
    18+12 final percentage points, not 5.4+3.6. Other explicit denominators are
    handled as observed_points / group_max * group_final_weight.
    """
    groups, current = {}, None
    for raw in text.splitlines():
        line = _plain_markup(raw).lstrip("# ")
        heading = None
        for key, label in (("first", _FIRST), ("second", _SECOND), ("final", r"final\s+exam|финальн\w*\s+экзамен")):
            match = re.search(label, line, re.I)
            if match and re.fullmatch(r"[\d.)\s-]*", line[:match.start()]):
                heading = key
                break
        if heading:
            if heading in groups:
                groups[heading]["repeated_heading"] = True
            current = groups.setdefault(heading, {"title": line[:160], "rows": [], "quote": raw.strip()})
            continue
        if current is None:
            continue
        maximum = re.search(rf"\bmax(?:imum)?\s*[:=]?\s*({_NUMBER})\s*points?\b", line, re.I)
        percent = re.search(rf"({_NUMBER})\s*%\s*(?:of\s+(?:the\s+)?)?final\s+grade", line, re.I)
        if maximum and percent:
            if ("maximum" in current and (current["maximum"] != _float(maximum[1])
                                          or current["weight"] != _float(percent[1]))):
                current["conflicting_weight"] = True
            current.update(maximum=_float(maximum[1]), weight=_float(percent[1]), weight_quote=raw.strip())
            continue
        points = _named_point_row(line)
        if points:
            current["rows"].append({**points, "quote": raw.strip()})
    if not any("maximum" in group for group in groups.values()):
        return None
    components, warnings = [], []
    if set(groups) != {"first", "second", "final"}:
        warnings.append("Не найдены все три раздела оценивания с явными максимумами; недостающие веса не подставлены.")
    total_outer = sum((Fraction(str(group.get("weight", 0))) for group in groups.values()), Fraction(0))
    if total_outer != 100:
        warnings.append(f"Внешние веса разделов составляют {float(total_outer):g}%, а не 100%; проверьте схему.")
    for key in ("first", "second", "final"):
        group = groups.get(key)
        if not group:
            continue
        if group.get("repeated_heading") or group.get("conflicting_weight"):
            warnings.append(f"{group['title']}: раздел или его максимум указан повторно/противоречиво; проверьте объединение строк вручную.")
        maximum, weight = group.get("maximum"), group.get("weight")
        if not maximum or not weight:
            warnings.append(f"{group['title']}: явный максимум и процент итоговой оценки не найдены.")
            continue
        observed = sum((Fraction(str(row["points"])) for row in group["rows"]), Fraction(0))
        if observed != Fraction(str(maximum)):
            warnings.append(f"{group['title']}: работы дают {float(observed):g} из {maximum:g} баллов; проверьте пропущенные или повторные строки.")
        for row in group["rows"]:
            if not 0 < row["points"] <= maximum or not 0 < weight <= 100:
                warnings.append(f"{row['name']}: баллы выходят за явный максимум раздела; строка пропущена.")
                continue
            global_weight = Fraction(str(row["points"])) / Fraction(str(maximum)) * Fraction(str(weight))
            components.append({"name": row["name"], "weight": round(float(global_weight), 6),
                               "score": None, "max_score": row["points"],
                               "source_quote": (row["quote"] + " | " + group["weight_quote"])[:1000]})
    # An explicit formula must agree with the independently observed section
    # weights. Do not let a convenient sum conceal contradictory evidence.
    outer, _, _ = _outer_formula(_plain_markup(text))
    if outer and any(key in groups and "weight" in groups[key] and abs(value - groups[key]["weight"]) > .000001
                     for key, value in outer.items()):
        warnings.append("Итоговая формула противоречит процентам разделов; схема не принята автоматически.")
        components = []
    if warnings and _complete_weights(components):
        components = []  # Compensating errors must not appear as a valid scheme.
    return components, warnings


def _policy_warnings(text):
    result = []
    for raw in text.splitlines():
        line = _plain_markup(raw).strip(" -*")
        if re.search(r"automatic\s+fail|automatically\s+fail|автоматическ\w*\s+(?:провал|неуд|отчисл)", line, re.I):
            result.append("Дополнительное правило силлабуса: " + line[:800] +
                          " Калькулятор взвешенных баллов не применяет это правило автоматически; проверьте пороги отдельно.")
        elif re.search(r"late\s+submissions?|просроченн\w*\s+(?:работ|сдач)", line, re.I):
            result.append("Правило сроков из силлабуса: " + line[:800] +
                          " Нулевые баллы за пропуск срока автоматически не выставляются.")
    return result


def _text(pages) -> tuple[str, list[str]]:
    warnings = []
    if isinstance(pages, str):
        value = pages
    elif isinstance(pages, (list, tuple)):
        selected = pages[:20]
        value = "\n\n".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in selected)
        if len(pages) > 20:
            warnings.append("Обработаны первые 20 страниц документа.")
    else:
        raise ValueError("Передайте текст силлабуса или список страниц с полем text")
    if len(value) > MAX_TEXT:
        warnings.append("Документ сокращён до 150 000 символов для безопасной обработки.")
        value = value[:MAX_TEXT]
    value = value.replace("\u00a0", " ").replace("−", "-").replace("–", "-").replace("×", "*")
    value = re.sub(r"([12])\s*[ˢⁿ][ᵗᵈ]", lambda m: m[1] + ("st" if m[1] == "1" else "nd"), value)
    value = re.sub(r"\bI\s*st(?=\s+att)", "1st", value, flags=re.I)
    value = re.sub(r"(\bassignment\s+)I\b", r"\g<1>1", value, flags=re.I)
    # OCR commonly places the ordinal and the section name on separate lines.
    value = re.sub(r"\b([12])\s*(st|nd|ая|я|й)?\s*\n\s*(attestation|аттестация)", r"\1\2 \3", value, flags=re.I)
    return value, warnings


def _float(value: str) -> float:
    return float(value.replace(",", "."))


def _course_name(text: str, supplied: str) -> str:
    match = re.search(r"(?:course\s+(?:title|name)|название\s+(?:курса|дисциплины)|наименование\s+дисциплины)\s*[:|\t ]*\s*([^\n|]+)", text, re.I)
    if match:
        value = match[1].strip(" :|\t")
        if value:
            return value[:120]
    if supplied and supplied.strip():
        fallback = supplied.replace("\\", "/").rsplit("/", 1)[-1].strip()
        fallback = re.sub(r"\.(?:pdf|txt|docx?|png|jpe?g|webp)$", "", fallback, flags=re.I)
        return fallback[:120] or "Новый предмет"
    return "Новый предмет"


def _outer_formula(text: str) -> tuple[dict[str, float], str, int | None]:
    """Read coefficient-before-period terms, never infer 30/30/40 by default."""
    labels = {"first": _FIRST, "second": _SECOND, "final": _FINAL}
    values, quotes, positions = {}, [], []
    for key, label in labels.items():
        pattern = rf"(?<![\d.])(?P<n>0[.,]\d+|\d+(?:[.,]\d+)?[ \t]*%)[ \t]*\*?[ \t]*(?P<label>{label})"
        match = re.search(pattern, text, re.I)
        # Percentage-after-label formulas also occur in tabular syllabi.
        if not match:
            pattern = rf"(?P<label>{label})\s*[:=|]?\s*(?P<n>\d+(?:[.,]\d+)?\s*%)"
            match = re.search(pattern, text, re.I)
        if match:
            raw = match["n"].strip()
            number = _float(raw.replace("%", "").strip())
            if "%" not in raw:
                number *= 100
            if 0 < number <= 100:
                values[key] = number
                quotes.append(match.group())
                positions.append(match.start())
    return values, " + ".join(quotes), min(positions) if positions else None


def _row_value(tail: str) -> float | None:
    # Column after the task name is its contribution, not the row's Total=100.
    match = re.search(rf"({_NUMBER})\s*%", tail) if "%" in tail else re.search(rf"(?:[:=|\t ]|^)+({_NUMBER})", tail)
    if match:
        value = _float(match[1])
        if 0 < value <= 100:
            return value
    return None


def _section_components(body: str, label: str, outer: float, outer_quote: str) -> tuple[list[dict], list[str]]:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    explicit, assignments, warnings = [], [], []
    pending = None
    aggregate = None
    aggregate_quote = ""
    aggregate_position = 0
    for position, line in enumerate(lines):
        # A plural "Assignments 40" is a subtotal, not an additional task.
        aggregate_match = re.search(r"(?:assignments|ассайнменты|задания)\s*\**\s*[:|]?\s*(.*)", line, re.I)
        if aggregate_match:
            aggregate = _row_value(aggregate_match[1])
            aggregate_quote, aggregate_position = line, position
            pending = ("aggregate", aggregate_match.group()) if aggregate is None else None
            continue
        component = _COMPONENT.search(line)
        if component:
            name = component.group().strip()
            value = _row_value(line[component.end():])
            record = {"name": name, "value": value, "quote": line, "position": position}
            if re.search(rf"^{_ASSIGNMENT}", name, re.I):
                assignments.append(record)
            else:
                explicit.append(record)
            pending = ("record", record) if value is None else None
        elif pending:
            # Pure numeric next-row values are observed table cells.
            numeric = re.fullmatch(rf"\s*({_NUMBER})\s*%?(?:\s+[|]?\s*100)?\s*", line)
            if numeric:
                value = _float(numeric[1])
                if 0 < value <= 100:
                    if pending[0] == "aggregate":
                        aggregate = value
                        aggregate_quote += " " + line
                    else:
                        pending[1]["value"] = value
                        pending[1]["quote"] += " " + line
                    pending = None
    known_assignments = [r for r in assignments if r["value"] is not None]
    if len(assignments) == 1 and not known_assignments and aggregate is not None:
        assignments[0]["value"] = aggregate
        assignments[0]["quote"] += f"; {aggregate_quote}"
        known_assignments = assignments[:]
    if aggregate is not None:
        child_sum = sum(r["value"] for r in known_assignments)
        if len(known_assignments) == len(assignments) and abs(child_sum - aggregate) < .01:
            explicit.extend(known_assignments)
        elif not known_assignments or len(known_assignments) < len(assignments):
            # Keep the observed subtotal until the user supplies the breakdown.
            explicit.append({"name": "Assignments", "value": aggregate, "quote": aggregate_quote, "position": aggregate_position})
            if len(assignments) > 1:
                warnings.append(f"{label}: вес заданий указан суммарно; уточните веса отдельных заданий.")
        else:
            warnings.append(f"{label}: сумма весов заданий {child_sum:g} не совпадает с подытогом {aggregate:g}; проверьте таблицу.")
            return [], warnings
    else:
        explicit.extend(known_assignments)
    missing = [r["name"] for r in explicit if r["value"] is None]
    if missing:
        warnings.append(f"{label}: не найдены веса: {', '.join(missing)}.")
    explicit = [r for r in explicit if r["value"] is not None]
    total = sum(r["value"] for r in explicit)
    if not explicit or abs(total - 100) > .01:
        warnings.append(f"{label}: распознано {total:g} из 100 внутренних баллов; недостающие веса не подставлены.")
    result = []
    for row in sorted(explicit, key=lambda r: r["position"]):
        result.append({"name": f"{label} · {row['name']}", "weight": round(row["value"] * outer / 100, 6),
                       "max_score": 100, "score": None,
                       "source_quote": f"{row['quote']} | {outer_quote}"[:1000]})
    return result, warnings


def parse_syllabus(pages, name: str = "") -> dict:
    """Extract a course draft, warnings and quoted evidence from syllabus text.

    `pages` accepts plain text or the PDF extractor's list of {text: ...} pages.
    A partial result is deliberately not a valid 100% grading scheme until the
    user supplies the missing evidence; callers must not normalize its weights.
    """
    text, warnings = _text(pages)
    readable = _plain_markup(text)
    course_name = _course_name(readable, name)
    credits_match = re.search(r"(?:number\s+of\s+credits|(?:ECTS\s+)?credits|количество\s+кредитов|кредиты|кредитов)\s*[:|\t ]*\s*(\d+(?:[.,]\d+)?)", readable, re.I)
    credits = _float(credits_match[1]) if credits_match else None
    if credits is not None and not 0 < credits <= 60:
        credits = None
    if credits is None:
        warnings.append("Кредиты предмета не найдены; укажите их вручную.")
    if course_name == "Новый предмет":
        warnings.append("Название предмета не найдено; укажите его вручную.")
    elif name and not re.search(r"course\s+(?:title|name)|название\s+(?:курса|дисциплины)|наименование\s+дисциплины", readable, re.I):
        warnings.append("Название предложено по имени файла или введённому имени, а не прочитано из силлабуса; подтвердите его вручную.")
    outer, formula_quote, formula_start = _outer_formula(text)
    components = []
    # Ignore formula text when identifying section headings and local task rows.
    full_formula = all(key in outer for key in ("first", "second", "final"))
    body = text[:formula_start] if full_formula and formula_start is not None else text
    first = re.search(_FIRST, body, re.I)
    second = re.search(_SECOND, body, re.I)
    final = re.search(_FINAL, body, re.I)
    hierarchy = bool(first or second)
    points = _global_point_scheme(text)
    if points is not None:
        components, point_notes = points
        warnings.extend(point_notes)
    elif hierarchy:
        if abs(sum(outer.values()) - 100) > .01 or not all(k in outer for k in ("first", "second", "final")):
            warnings.append("Найдены аттестации, но полная итоговая формула не распознана. Внутренние баллы не считаются процентами всего курса.")
        else:
            for key, start, end, label in (
                ("first", first, second or final, "1st attestation"),
                ("second", second, final, "2nd attestation"),
            ):
                if not start:
                    warnings.append(f"Не найдена таблица {label}; её веса не подставлены.")
                    continue
                end_pos = end.start() if end and end.start() > start.start() else len(body)
                extracted, notes = _section_components(body[start.end():end_pos], label, outer[key], formula_quote)
                components.extend(extracted)
                warnings.extend(notes)
            components.append({"name": "Final exam", "weight": round(outer["final"], 6),
                               "max_score": 100, "score": None, "source_quote": formula_quote[:1000]})
    else:
        # Flat schemes require explicit percentages, or explicit weights/points
        # table headings and a total of 100. Bare numbers are too ambiguous.
        table_weights = bool(re.search(r"(?:weight|вес|доля|percentage|number\s+of\s+points|балл\w*)", body, re.I))
        for original_line in body.splitlines():
            line = _plain_markup(original_line)
            if _policy_or_total_row(line):
                continue
            match = _COMPONENT.search(line)
            generic = re.fullmatch(rf"\s*[-*•]?\s*(.+?)\s*(?:[—:|=-]\s*|\s+)({_NUMBER})\s*%\s*", line)
            if generic and not re.search(r"\b(?:score|weight)\b", generic[1], re.I):
                title, value = generic[1].strip(" |:—-"), _float(generic[2])
                if not title or not 0 < value <= 100:
                    continue
            else:
                if not match:
                    continue
                tail = line[match.end():]
                value = _row_value(tail)
                if value is None or ("%" not in tail and not table_weights):
                    continue
                title = match.group().strip()
            if any(c["name"].casefold() == title.casefold() for c in components):
                warnings.append(f"Повтор строки {title}: проверьте, что её вес указан один раз.")
                continue
            components.append({"name": title, "weight": value, "max_score": 100,
                               "score": None, "source_quote": original_line.strip()[:1000]})
    total_weight = sum(c["weight"] for c in components)
    if not components:
        warnings.append("Веса оценочных работ не распознаны. Вставьте таблицу оценивания или уточните проценты вручную.")
    elif not _complete_weights(components):
        warnings.append(f"Сумма распознанных весов {total_weight:g}%, а должна быть 100%. Проверьте схему перед сохранением.")
    if len(components) > 40:
        components = components[:40]
        warnings.append("Найдено более 40 компонентов; список сокращён. Проверьте итоговую сумму.")
    for index, component in enumerate(components):
        component["id"] = f"assessment-{index + 1}"
    confidence = .95 if components and _complete_weights(components) else (.4 if components else .1)
    if credits is None or course_name == "Новый предмет":
        confidence = max(.1, confidence - .15)
    if points is not None and points[1]:
        confidence = min(confidence, .4)
    if points is not None and components:
        warnings.append("Максимумы работ взяты из явно указанных points/баллов. Оценки вводятся в баллах каждой работы, а веса — в процентах курса; проверьте поле «Максимум».")
    policies = _policy_warnings(text)
    warnings.extend(policies)
    return {"course": {"name": course_name, "credits": credits, "difficulty": None,
                       "target": 95, "term": "trimester", "components": components},
            "warnings": list(dict.fromkeys(warnings)), "policy_warnings": policies,
            "confidence": round(confidence, 2), "source_text": text}


_WEEKDAYS = {name: index for index, names in enumerate((
    ("monday", "понедельник"), ("tuesday", "вторник"), ("wednesday", "среда"),
    ("thursday", "четверг"), ("friday", "пятница"), ("saturday", "суббота"), ("sunday", "воскресенье"),
)) for name in names}


def _weekly_schedule(text, zone, anchor_date, weeks, original_rows):
    # A dated exam table is not evidence for weekly classes.
    if any(re.match(r"\d{1,2}[./]\d{1,2}(?:[./]20\d{2})?(?!\d)", _plain_markup(row).lstrip("# -*")) for row in text.splitlines()):
        return None
    rules, warnings, weekday = [], [], None
    for raw in text.splitlines():
        line = _plain_markup(raw).strip("# ")
        heading = re.fullmatch(r"([A-Za-zА-Яа-яЁё]+)(?:\s*\([^)]*\))?\s*[:：]?", line)
        if heading and heading[1].casefold() in _WEEKDAYS:
            weekday = _WEEKDAYS[heading[1].casefold()]
            continue
        inline = re.fullmatch(r"([A-Za-zА-Яа-яЁё]+)(?:\s*\([^)]*\))?\s*[:：]\s*(.+)", line)
        if inline and inline[1].casefold() in _WEEKDAYS:
            weekday = _WEEKDAYS[inline[1].casefold()]
            line = inline[2]
            if re.match(r"\d{1,2}[./]\d{1,2}(?:[./]20\d{2})?(?!\d)", line):
                return None  # An observed date must never be repeated as a weekday rule.
        time_match = _TIME_RANGE.search(line)
        if weekday is None or not time_match:
            continue
        tail = line[time_match.end():].strip(" |\t;,-—")
        columns = [part.strip() for part in tail.split("|")]
        title = columns[0][:160]
        kind = columns[1][:80] if len(columns) > 1 else ""
        if re.search(r"\bexamfx?\b|\bexam\b|экзамен|midterm|endterm", kind, re.I):
            warnings.append("Недатированный экзамен не превращён в еженедельное занятие; укажите его точную дату отдельно.")
            continue
        start_time = f"{int(time_match[1]):02d}:{time_match[2]}"
        end_time = f"{int(time_match[3]):02d}:{time_match[4]}"
        if not title or end_time <= start_time:
            warnings.append(f"Не распознано название или неверный интервал занятия: {raw[:120]}")
            continue
        rules.append({"weekday": weekday, "start_time": start_time, "end_time": end_time,
                      "title": title, "course": title, "kind": kind,
                      "room": columns[2][:160] if len(columns) > 2 else "",
                      "source_quote": original_rows.get(raw, raw)[:1000]})
    if not rules:
        return None
    unique = {(row["weekday"], row["start_time"], row["end_time"], row["title"]): row for row in rules}
    rules = sorted(unique.values(), key=lambda row: (row["weekday"], row["start_time"], row["title"]))
    if len(rules) > 500:
        warnings.append(f"Распознано {len(rules)} строк, обработаны первые 500; разделите расписание и проверьте покрытие.")
        rules = rules[:500]
    try:
        requested_weeks = int(weeks)
        if isinstance(weeks, bool) or requested_weeks != float(weeks) or not 1 <= requested_weeks <= 20:
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Повторение расписания должно быть от 1 до 20 целых недель") from None
    try:
        anchor = (anchor_date.date() if isinstance(anchor_date, datetime) else anchor_date
                  if isinstance(anchor_date, date) else date.fromisoformat(str(anchor_date))
                  if anchor_date else datetime.now(zone).date())
    except (TypeError, ValueError):
        raise ValueError("Укажите начало недели в формате ГГГГ-ММ-ДД") from None
    monday = anchor - timedelta(days=anchor.weekday())
    if not anchor_date:
        warnings.append(f"Дата начала не указана: выбрана текущая неделя с {monday.isoformat()}. При необходимости выберите следующую.")
    elif anchor != monday:
        warnings.append(f"Для выбранной даты используется начало недели в понедельник {monday.isoformat()}.")
    selected_weeks = min(requested_weeks, max(1, 500 // len(rules)))
    if selected_weeks != requested_weeks:
        warnings.append(f"Для лимита 500 интервалов период сокращён до {selected_weeks} недель; проверьте дату окончания.")
    beginning = datetime.combine(monday, datetime.min.time(), tzinfo=zone)
    busy = []
    for week in range(selected_weeks):
        for rule in rules:
            day = beginning + timedelta(days=week * 7 + rule["weekday"])
            start = day.replace(hour=int(rule["start_time"][:2]), minute=int(rule["start_time"][3:]))
            end = day.replace(hour=int(rule["end_time"][:2]), minute=int(rule["end_time"][3:]))
            busy.append({"start": start.isoformat(), "end": end.isoformat(), "title": rule["title"]})
    coverage_end = monday + timedelta(weeks=selected_weeks, days=-1)
    warnings.append(f"Еженедельные занятия повторены на {selected_weeks} недель: {monday.isoformat()} — {coverage_end.isoformat()}. "
                    "После этой даты расписание нужно продлить; каникулы и отмены автоматически не известны.")
    return {"busy": busy, "exams": [], "weekly_rules": rules, "courses": list(dict.fromkeys(row["course"] for row in rules)),
            "weekly_count": len(rules), "warnings": list(dict.fromkeys(warnings)), "year": monday.year,
            "timezone": str(zone), "recurring": True, "week_start": monday.isoformat(),
            "coverage_end": coverage_end.isoformat(), "weeks": selected_weeks}


def parse_schedule(text: str, year: int | None = None, timezone_name: str = "Asia/Almaty",
                   anchor_date: str | date | None = None, weeks: int = 12) -> dict:
    """Read dated exam/timetable rows, including cells whose date spans rows.

    Explicit weekday headings produce a bounded weekly-class preview, with a
    disclosed editable start week and coverage end. Dated exam rows retain only
    their observed dates and are never shifted or repeated.
    """
    # Parsing normalizes OCR punctuation, while provenance keeps original rows.
    original_rows = {_text(row)[0]: row for row in str(text)[:MAX_TEXT].splitlines()}
    text, warnings = _text(text)
    zone = ZoneInfo(timezone_name)
    weekly = _weekly_schedule(text, zone, anchor_date, weeks, original_rows)
    if weekly is not None:
        weekly["warnings"] = list(dict.fromkeys(warnings + weekly["warnings"]))
        return weekly
    observed_year = re.search(r"\b(20\d{2})\b", text)
    selected_year = int(year or (observed_year[1] if observed_year else datetime.now(zone).year))
    if not 2000 <= selected_year <= 2100:
        raise ValueError("Год расписания должен быть между 2000 и 2100")
    if year is None and observed_year is None:
        warnings.append(f"Год не указан: используется {selected_year}. Проверьте даты перед сохранением.")
    busy, exams = [], []
    current_date = None
    # Only a leading date cell counts: classroom C1.1.228 is not 1 January.
    date_re = re.compile(r"^\s*(\d{1,2})[./](\d{1,2})(?:[./](20\d{2}))?(?!\d)")
    range_re = _TIME_RANGE
    for line in text.splitlines():
        date_match = date_re.search(line)
        if date_match:
            try:
                current_date = datetime(int(date_match[3] or selected_year), int(date_match[2]), int(date_match[1]), tzinfo=zone)
            except ValueError:
                current_date = None
                warnings.append(f"Некорректная дата в строке: {line[:100]}")
                continue
        time_match = range_re.search(line)
        if not time_match:
            continue
        if current_date is None:
            warnings.append(f"Не найдена дата для интервала {time_match.group()}; он не добавлен.")
            continue
        start = current_date.replace(hour=int(time_match[1]), minute=int(time_match[2]))
        end = current_date.replace(hour=int(time_match[3]), minute=int(time_match[4]))
        if end <= start:
            warnings.append(f"Конец занятия раньше начала: {line[:100]}")
            continue
        title = line[time_match.end():].strip(" |\t;,-")
        # Remaining table columns are classroom, exam type and lecturer.
        title = re.split(r"\s*\|\s*|\t+|\s{2,}|\s+C\d[.\dA-Za-z]+\b|\s+(?:examfx?|экзамен)\b", title, maxsplit=1, flags=re.I)[0].strip()
        if not title:
            title = "Занятие / экзамен"
        busy.append({"start": start.isoformat(), "end": end.isoformat(), "title": title[:160]})
        if (re.search(rf"\b(?:examf?|examfx|экзамен)\b|{_MID}|{_END}", line, re.I)
                or re.search(r"exam|экзамен", text[:700], re.I)):
            if re.search(_MID, line, re.I):
                kind = "midterm"
            elif re.search(_END, line, re.I):
                kind = "endterm"
            elif re.search(rf"\bexamfx?\b|{_FINAL}", line, re.I):
                kind = "final"
            else:
                kind = "exam"
            exams.append({"title": f"Экзамен: {title}"[:160], "course": title[:80],
                          "due_at": start.isoformat(), "assessment_kind": kind,
                          "source_quote": original_rows.get(line, line)[:1000]})
    if not busy:
        warnings.append("Датированные занятия не распознаны. Нужны дата, время начала и окончания.")
    elif all(datetime.fromisoformat(block["end"]) < datetime.now(zone) for block in busy):
        warnings.append("Все распознанные даты уже прошли. Они сохранены как в источнике, без переноса на будущую неделю.")
    unique = {(b["start"], b["end"], b["title"]): b for b in busy}
    exam_unique = {(e["course"], e["due_at"]): e for e in exams}
    return {"busy": sorted(unique.values(), key=lambda b: b["start"]),
            "exams": sorted(exam_unique.values(), key=lambda e: e["due_at"]),
            "warnings": list(dict.fromkeys(warnings)), "year": selected_year,
            "timezone": timezone_name, "recurring": False}
