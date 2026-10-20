"""Connect explicitly identified imported exams to their exact course assessments."""
from copy import deepcopy
from datetime import datetime, timezone
import re


def _normalized(value):
    value = re.sub(r"\s*[·—-]\s*пример\s*$", "", str(value), flags=re.I)
    return re.sub(r"[^\w]+", "", value.casefold())


def _names(value):
    names = {_normalized(value)}
    names.add(_normalized(re.sub(r"\([^)]*\)", "", str(value))))
    names.update(_normalized(part) for part in re.findall(r"\(([A-ZА-Я0-9]{2,10})\)", str(value)))
    return names - {""}


def apply_exam_schedule(courses, schedule, now=None):
    """Return copies. Never change saved grades, weights or user-entered deadlines.

    A generic 'exam' is not assumed to be a final. An exact course match and a
    unique, explicit final/midterm/endterm assessment are required to link dates.
    """
    result = deepcopy(courses)
    notes = []
    now = now or datetime.now(timezone.utc)
    patterns = {"final": r"\bfinal\b|финал|итоговый\s+экзамен",
                "midterm": r"mid\s*term|мидтерм|промежуточный\s+экзамен",
                "endterm": r"end\s*term|эндтерм|ендтерм"}
    by_assessment = {}
    for exam in (schedule or {}).get("exams", []):
        matches = [c for c in result if _names(c["name"]) & _names(exam.get("course", ""))]
        if len(matches) != 1:
            notes.append(f"Экзамен «{exam.get('course', '')}»: нет единственного совпадения с сохранёнными предметами. Дата не назначена работе.")
            continue
        kind = exam.get("assessment_kind", "exam")
        if kind not in patterns:
            notes.append(f"«{exam.get('course', '')}»: в расписании не указан вид экзамена. Укажите дедлайн нужной работы вручную.")
            continue
        course = matches[0]
        assessments = [a for a in course["components"] if a.get("score") is None and re.search(patterns[kind], a["name"], re.I)]
        if len(assessments) != 1:
            notes.append(f"«{course['name']}»: не найдена единственная неоценённая работа для экзамена {kind}. Даты работ оставлены без изменений.")
            continue
        component = assessments[0]
        if component.get("due_at"):
            continue
        try:
            due = datetime.fromisoformat(exam["due_at"])
            if due.tzinfo is None:
                continue
        except (ValueError, KeyError, TypeError):
            continue
        key = (course.get("id", course["name"]), component.get("id", component["name"]))
        by_assessment.setdefault(key, (course, component, []))[2].append(due)
    for course, component, dates in by_assessment.values():
        future = [date for date in dates if date > now]
        due = min(future) if future else max(dates)
        component["due_at"] = due.isoformat()
        quote = f"Дата «{component['name']}» взята из подтверждённого расписания: {due.isoformat()}"
        course.setdefault("_schedule_links", []).append(quote)
        if len(dates) > 1:
            notes.append(f"«{course['name']}»: найдено несколько дат одного экзамена; для подготовки выбрана ближайшая будущая, либо последняя прошедшая.")
    return result, list(dict.fromkeys(notes))
