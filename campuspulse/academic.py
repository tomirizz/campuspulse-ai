"""Auditable course grades, reachable goals, and academic priorities.

Assessment weights are percentages of the *whole course*, not of an attestation.
There is no unique minimum for several unknown grades: ``balanced_plan`` keeps
their normalized percentages equal, while ``conditional_min_score`` assumes
every OTHER unfinished assessment receives its maximum. Those conditional
minima must never be presented as one jointly achievable plan.
"""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RULE_VERSION = "academic-v1"
TARGETS = (95, 90, 85, 80, 75, 70)
TARGET_LABELS = {
    95: "Excellent", 90: "Great", 85: "Very good", 80: "Good",
    75: "Not bad", 70: "Scholarship saver",
}
DEFAULT_GRADE_SCALE = [
    {"min_score": 95, "letter": "A", "gpa": 4.0, "label": "Excellent"},
    {"min_score": 90, "letter": "A-", "gpa": 3.67, "label": "Great"},
    {"min_score": 85, "letter": "B+", "gpa": 3.33, "label": "Very good"},
    {"min_score": 80, "letter": "B", "gpa": 3.0, "label": "Good"},
    {"min_score": 75, "letter": "B-", "gpa": 2.67, "label": "Not bad"},
    {"min_score": 70, "letter": "C+", "gpa": 2.0, "label": "Scholarship saver"},
    {"min_score": 65, "letter": "C", "gpa": 1.67, "label": "Satisfactory"},
    {"min_score": 60, "letter": "C-", "gpa": 1.33, "label": "Satisfactory"},
    {"min_score": 55, "letter": "D+", "gpa": 1.0, "label": "Pass"},
    {"min_score": 50, "letter": "D", "gpa": 0.67, "label": "Pass"},
    {"min_score": 0, "letter": "F", "gpa": 0.0, "label": "Below passing"},
]


def default_grade_scale():
    """Return an independent, editable sample scale; university rules may differ."""
    return deepcopy(DEFAULT_GRADE_SCALE)


class GradeBand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    min_score: float = Field(ge=0, le=100, allow_inf_nan=False)
    letter: str = Field(min_length=1, max_length=20)
    gpa: float = Field(ge=0, le=5, allow_inf_nan=False)
    label: str = Field(default="", max_length=100)


class AcademicBusyBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    start: datetime
    end: datetime
    title: str = Field(default="Занято", max_length=160)

    @field_validator("start", "end")
    @classmethod
    def aware_date(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Укажите дату с часовым поясом, например +05:00")
        return value

    @model_validator(mode="after")
    def positive_duration(self):
        if self.end <= self.start:
            raise ValueError("Конец занятого времени должен быть позже начала")
        return self


class AcademicSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)
    preferred_target: float = Field(default=95, ge=0, le=100, allow_inf_nan=False)
    min_target: float = Field(default=70, ge=0, le=100, allow_inf_nan=False)
    timezone: str = "Asia/Almaty"
    daily_minutes: int = Field(default=180, ge=15, le=600)
    start_hour: int = Field(default=16, ge=0, le=23)
    end_hour: int = Field(default=22, ge=1, le=24)
    busy: list[AcademicBusyBlock] = Field(default_factory=list, max_length=5000)
    grade_scale: list[GradeBand] = Field(default_factory=default_grade_scale, min_length=1, max_length=30)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("Неизвестный часовой пояс") from exc
        return value

    @model_validator(mode="after")
    def consistent_settings(self):
        if self.min_target > self.preferred_target:
            raise ValueError("Минимальная цель не может быть выше желаемой")
        if self.start_hour >= self.end_hour:
            raise ValueError("Конец учебного окна должен быть позже начала")
        _validated_scale(self.grade_scale)
        return self


class AssessmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str | None = Field(default=None, min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    weight: float = Field(gt=0, le=100, allow_inf_nan=False)
    score: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_score: float = Field(default=100, gt=0, le=100000, allow_inf_nan=False)
    due_at: datetime | None = None
    estimated_minutes: int = Field(default=120, ge=15, le=2400)
    source_quote: str | None = Field(default=None, max_length=4000)

    @field_validator("due_at")
    @classmethod
    def aware_due_date(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Укажите дедлайн с часовым поясом, например +05:00")
        return value

    @model_validator(mode="after")
    def score_within_maximum(self):
        if self.score is not None and self.score > self.max_score:
            raise ValueError("Полученный балл не может превышать максимальный")
        return self


class CourseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)
    credits: float = Field(default=5, ge=0.5, le=30, allow_inf_nan=False)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    target: float = Field(default=95, ge=0, le=100, allow_inf_nan=False)
    term: Literal["semester", "trimester"] = "trimester"
    material_ids: list[str] = Field(default_factory=list, max_length=10)
    policy_warnings: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=10)
    components: list[AssessmentInput] = Field(min_length=1, max_length=40)

    @field_validator("material_ids")
    @classmethod
    def source_ids(cls, value):
        if any(not 1 <= len(item) <= 100 for item in value):
            raise ValueError("Проверьте идентификаторы учебных материалов")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def valid_components(self):
        total = sum((_decimal(c.weight) for c in self.components), Decimal(0))
        if abs(total - 100) > Decimal("0.000001"):
            raise ValueError(f"Веса всех заданий должны составлять 100%, сейчас {total}%")
        ids = [c.id for c in self.components if c.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("Идентификаторы заданий не должны повторяться")
        return self


def _decimal(value):
    if isinstance(value, Fraction):
        return Decimal(value.numerator) / Decimal(value.denominator)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _fraction(value):
    return value if isinstance(value, Fraction) else Fraction(_decimal(value))


def _number(value, digits=6):
    """Convert for JSON only; decisions and ceilings use exact rational values."""
    if value is None:
        return None
    rounded = _decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(rounded)


def _validated_scale(scale):
    bands = [v if isinstance(v, GradeBand) else GradeBand.model_validate(v) for v in scale]
    thresholds = [band.min_score for band in bands]
    if len(thresholds) != len(set(thresholds)) or 0 not in thresholds:
        raise ValueError("Шкала GPA должна содержать порог 0 и уникальные пороги")
    ordered = sorted(bands, key=lambda band: band.min_score, reverse=True)
    if any(a.gpa < b.gpa for a, b in zip(ordered, ordered[1:])):
        raise ValueError("GPA не должен уменьшаться при росте балла")
    return ordered


def grade_for_score(score, scale=None):
    if score is None:
        return None
    try:
        value = _fraction(score)
    except (ValueError, OverflowError):
        raise ValueError("Итоговый процент должен быть от 0 до 100") from None
    if not 0 <= value <= 100:
        raise ValueError("Итоговый процент должен быть от 0 до 100")
    for band in _validated_scale(scale if scale is not None else DEFAULT_GRADE_SCALE):
        if value >= _fraction(band.min_score):
            return band.model_dump()
    raise ValueError("Шкала оценок не покрывает этот процент")


# Friendly public alias used by clients that only need the grade conversion.
grade_scale = grade_for_score


def _difficulty(course):
    if course.difficulty is not None:
        return course.difficulty, "Ваша оценка сложности"
    title = course.name.casefold()
    if any(word in title for word in ("high performance", "hpc", "stochastic", "стохаст", "квант")):
        value = 5
    elif any(word in title for word in ("math", "mathem", "математ", "algorithm", "алгоритм", "statistics", "статист", "computational", "optimization", "оптимизац", "physics", "физик", "programming", "программ")):
        value = 4
    elif any(word in title for word in ("writing", "english", "письм", "английск")):
        value = 2
    else:
        value = 3
    return value, "Предварительно по названию предмета; измените под себя"


def _score_ceiling(percent, maximum):
    maximum = _fraction(maximum)
    # Whole-point plan by default. Fractional assessment maxima use hundredths.
    step = Fraction(1) if maximum.denominator == 1 else Fraction(1, 100)
    raw = max(Fraction(0), _fraction(percent)) * maximum / 100
    units = raw / step
    rounded_units = -(-units.numerator // units.denominator)
    return min(maximum, rounded_units * step)


def _scenario(target, earned, remaining, remaining_weight, scale):
    target = _fraction(target)
    maximum = earned + remaining_weight
    feasible = target <= maximum
    required = max(Fraction(0), target - earned)
    average = required * 100 / remaining_weight if remaining_weight else None
    plan = []
    projected = earned
    for item in remaining:
        weight, maximum_raw = item["_weight"], _fraction(item["max_score"])
        public = {k: v for k, v in item.items() if not k.startswith("_")}
        if feasible:
            balanced_score = _score_ceiling(average or Fraction(0), maximum_raw)
            balanced_percent = balanced_score / maximum_raw * 100
            conditional_percent = max(Fraction(0), (required - (remaining_weight - weight)) * 100 / weight)
            conditional_score = _score_ceiling(conditional_percent, maximum_raw)
            projected += weight * balanced_score / maximum_raw
            public.update(
                required_score=float(balanced_score),
                required_percent=_number(balanced_percent),
                conditional_min_score=float(conditional_score),
                conditional_min_percent=_number(conditional_score / maximum_raw * 100),
            )
        else:
            public.update(required_score=None, required_percent=None,
                          conditional_min_score=None, conditional_min_percent=None)
        plan.append(public)
    grade = grade_for_score(target, scale)
    return {
        "target": float(target), "label": TARGET_LABELS.get(float(target), grade["label"]),
        "gpa": grade["gpa"], "letter": grade["letter"], "feasible": feasible,
        "already_secured": earned >= target, "required_average": _number(average),
        "balanced_plan": plan, "projected_total": _number(projected) if feasible else None,
        "max_achievable": _number(maximum),
    }


def _task_due(task):
    value = task.get("due_at")
    try:
        date = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return date if date.tzinfo is not None and date.utcoffset() is not None else None


def analyze_course(course, tasks=None, now=None, grade_scale=None, min_target=70):
    """Return JSON-ready grade calculations and transparent priority reasons.

    ``current_average`` describes only assessments with recorded grades;
    ``earned_points`` describes secured points out of the final 100. A zero is
    recorded work, while a null score remains unfinished/awaiting a grade.
    """
    # Stored courses carry an application-generated id; input payload validation
    # stays strict in CourseInput, while analysis accepts that persistence field.
    course_id = course.get("id") if isinstance(course, dict) else None
    course = course if isinstance(course, CourseInput) else CourseInput.model_validate({key: value for key, value in course.items() if key != "id"})
    scale = [band.model_dump() for band in _validated_scale(grade_scale if grade_scale is not None else DEFAULT_GRADE_SCALE)]
    configured_floor = _decimal(min_target)
    if not configured_floor.is_finite() or not 0 <= configured_floor <= 100:
        raise ValueError("Минимальная цель должна быть от 0 до 100")
    desired = _fraction(course.target)
    # A personal course goal may intentionally be below the general fallback
    # floor (for example, a pass at 60). It remains a valid attainable goal.
    floor = min(_fraction(configured_floor), desired)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Текущее время должно включать часовой пояс")
    with localcontext() as context:
        context.prec = 40
        total = sum((_fraction(item.weight) for item in course.components), Fraction(0))
        components, remaining = [], []
        earned, completed_weight, assigned_weight = Fraction(0), Fraction(0), Fraction(0)
        reserved_ids = {component.id for component in course.components if component.id is not None}
        used_ids = set()
        for index, component in enumerate(course.components):
            public = component.model_dump(mode="json")
            if public["id"] is None:
                generated = f"assessment-{index + 1}"
                suffix = 1
                while generated in reserved_ids or generated in used_ids:
                    suffix += 1
                    generated = f"assessment-{index + 1}-{suffix}"
                public["id"] = generated
            used_ids.add(public["id"])
            weight = (100 - assigned_weight) if index == len(course.components) - 1 else _fraction(component.weight) * 100 / total
            assigned_weight += weight
            components.append(public)
            if component.score is None:
                remaining.append({**public, "_weight": weight})
            else:
                earned += weight * _fraction(component.score) / _fraction(component.max_score)
                completed_weight += weight
        remaining_weight = sum((item["_weight"] for item in remaining), Fraction(0))
        maximum = earned + remaining_weight
        current = earned * 100 / completed_weight if completed_weight else None
        targets = sorted({*(_fraction(goal) for goal in TARGETS), desired, floor}, reverse=True)
        scenarios = [_scenario(goal, earned, remaining, remaining_weight, scale) for goal in targets]
        # Compare exact inputs, not the rounded display values of scenarios.
        candidates = [s for goal, s in zip(targets, scenarios) if floor <= goal <= desired and s["feasible"]]
        active = candidates[0] if candidates else None
        active_target = active["target"] if active else None
        lowered = active_target is None or _fraction(active_target) < desired
        difficulty, difficulty_source = _difficulty(course)
        required_average = active["required_average"] if active else None
        if not remaining:
            risk = "complete"
        elif maximum < floor:
            risk = "critical"
        elif lowered:
            risk = "high"
        elif not completed_weight:
            risk = "ungraded"
        elif (required_average is not None and required_average > 90
              and current is not None and active_target is not None and current < _fraction(active_target)):
            risk = "high"
        elif current is not None and active_target is not None and current < _decimal(active_target):
            risk = "medium"
        else:
            risk = "low"
        dates = [_task_due(item) for item in remaining]
        for task in tasks or []:
            if hasattr(task, "model_dump"):
                task = task.model_dump(mode="json")
            if not task.get("completed") and str(task.get("course", "")).strip().casefold() == course.name.casefold():
                dates.append(_task_due(task))
        dates = [date for date in dates if date is not None]
        closest = min(dates) if dates else None
        days = (closest - now).total_seconds() / 86400 if closest else None
        urgency = 30 if days is not None and days < 0 else 25 if days is not None and days <= 1 else 20 if days is not None and days <= 3 else 12 if days is not None and days <= 7 else 6 if days is not None and days <= 14 else 0
        risk_points = {"critical": 55, "high": 40, "medium": 25, "low": 10, "ungraded": 15, "complete": 0}[risk]
        credit_points = min(course.credits, 10) * 1.5
        difficulty_points = difficulty * 2
        # Automatic fallback must not make a worsening course look healthier.
        # Compare observed performance to the student's original desired goal.
        comparison_target = _fraction(course.target)
        deficit_points = min(20.0, max(0.0, float(comparison_target - current)) * 0.75) if current is not None else 0.0
        priority_score = 0 if not remaining else risk_points + urgency + credit_points + difficulty_points + deficit_points
        reasons = []
        if risk == "complete":
            reasons.append("Все оценки внесены; учебное время не назначается")
        elif active is None:
            reasons.append(f"Цель {float(floor):g} уже недостижима; максимум {_number(maximum):g}")
        elif lowered:
            reasons.append(f"Цель {course.target:g} недостижима; рабочая цель {active_target:g}")
        elif current is not None:
            reasons.append(f"Текущий средний {_number(current):g}%; для цели нужно {required_average:g}% на оставшемся" if required_average is not None else "Все оценки внесены")
        else:
            reasons.append("Оценок пока нет; приоритет предварительный")
        if closest and remaining:
            reasons.append("Есть просроченное задание" if days < 0 else f"Ближайший дедлайн через {max(0, round(days, 1)):g} дн.")
        if remaining:
            reasons.extend([f"Кредиты: {course.credits:g}", f"Сложность: {difficulty}/5"])
        result = {
            **course.model_dump(mode="json"), "components": components,
            "difficulty": difficulty, "difficulty_source": difficulty_source,
            "earned_points": _number(earned), "completed_weight": _number(completed_weight),
            "remaining_weight": _number(remaining_weight), "current_average": _number(current),
            "max_achievable": _number(maximum), "active_target": active_target,
            "target_lowered": lowered, "target_unreachable": maximum < desired,
            "required_average": required_average,
            "balanced_plan": active["balanced_plan"] if active else [],
            "remaining_components": active["balanced_plan"] if active else [{k: v for k, v in item.items() if not k.startswith("_")} for item in remaining],
            "projected_total": active["projected_total"] if active else None,
            "scenarios": scenarios, "grade": grade_for_score(current, scale),
            "grade_is_provisional": bool(remaining), "final_grade": grade_for_score(earned, scale) if not remaining else None,
            "risk": risk, "priority_score": round(priority_score, 2), "priority_reasons": reasons,
            "nearest_deadline": closest.isoformat() if closest else None,
            "formula": "Итог = Σ(балл / максимум задания × вес задания в итоговой оценке)",
            "plan_note": "Это равномерный план: одинаковый процент на оставшихся работах, с округлением вверх до целого балла (до сотых при дробном максимуме). Его можно перераспределить между работами. Условный минимум одной работы предполагает 100% на ВСЕХ остальных; эти минимумы нельзя складывать в один план.",
            "gpa_note": "Редактируемая личная шкала: 70 → GPA 2.0, 65 → 1.67 подтверждены пользователем; остальные пороги предварительные. Scholarship saver — мотивационная метка, не гарантия стипендии; проверьте правила вуза.",
            "evidence": {
                "rule_version": RULE_VERSION, "weight_source": "Подтверждённая схема оценивания пользователя / силлабуса",
                "weight_total": _number(total), "score_source": "Только явно введённые оценки; пустое поле не считается нулём",
                "current_formula": "текущий средний = уже набранные итоговые баллы / проверенный вес × 100",
                "maximum_formula": "максимум = уже набранные итоговые баллы + оставшийся вес",
                "required_formula": "нужный средний = max(0, цель − набранные итоговые баллы) / оставшийся вес × 100",
                "conditional_formula": "минимум одной работы = max(0, цель − набрано − вес всех других оставшихся работ) / вес этой работы × её максимум",
                "priority_formula": "риск + близость дедлайна + 1.5 × min(кредиты, 10) + 2 × сложность + min(20, 0.75 × max(0, желаемая цель − текущий средний)); завершённый предмет = 0",
                "priority_inputs": {"risk": risk_points, "urgency": urgency, "credits": credit_points, "difficulty": difficulty_points, "grade_deficit": round(deficit_points, 4)},
                "grade_scale": scale,
            },
        }
        if course_id is not None:
            result["id"] = course_id
        return result


def academic_summary(analyzed_courses):
    """Credit-weighted, provisional GPA; ungraded courses never become zero."""
    courses = list(analyzed_courses)
    total_credits = sum((_decimal(c["credits"]) for c in courses), Decimal(0))
    graded = [c for c in courses if c.get("current_average") is not None and c.get("grade") is not None]
    graded_credits = sum((_decimal(c["credits"]) for c in graded), Decimal(0))
    projections, unprojected = [], []
    for course in courses:
        final_grade = course.get("final_grade")
        if final_grade is not None:
            # A finalized result, including an F/0, cannot become a lower
            # personal target or disappear from the overall GPA denominator.
            projections.append((course, final_grade["gpa"]))
        elif course.get("active_target") is not None:
            target = next(s for s in course["scenarios"] if s["target"] == course["active_target"])
            projections.append((course, target["gpa"]))
        else:
            unprojected.append(course["name"])
    projected_credits = sum((_decimal(c["credits"]) for c, _ in projections), Decimal(0))
    current_gpa = sum((_decimal(c["credits"]) * _decimal(c["grade"]["gpa"]) for c in graded), Decimal(0)) / graded_credits if graded_credits else None
    average = sum((_decimal(c["credits"]) * _decimal(c["current_average"]) for c in graded), Decimal(0)) / graded_credits if graded_credits else None
    # An overall projection is undefined if an unfinished course has no
    # reachable goal. Do not silently exclude that difficult course.
    target_gpa = sum((_decimal(c["credits"]) * _decimal(gpa) for c, gpa in projections), Decimal(0)) / projected_credits if projected_credits and not unprojected else None
    ranked = sorted(courses, key=lambda course: (-course["priority_score"], course["name"].casefold()))
    return {
        "course_count": len(courses), "total_credits": _number(total_credits),
        "graded_credits": _number(graded_credits), "graded_courses": len(graded),
        "current_gpa": _number(current_gpa, 2), "projected_gpa": _number(target_gpa, 2),
        "projected_credits": _number(projected_credits), "unprojected_courses": unprojected,
        "target_gpa": _number(target_gpa, 2), "average_current": _number(average, 2),
        "at_risk": sum(c["risk"] in {"critical", "high"} for c in courses),
        "at_risk_names": [c["name"] for c in ranked if c["risk"] in {"critical", "high"}],
        "ranked_courses": ranked,
        "gpa_note": "Текущий GPA предварительный: средние по внесённым оценкам взвешены по кредитам; предметы без оценок исключены. Целевой GPA — сценарий достижения рабочих целей, не прогноз; завершённые предметы входят с фактическим итогом, включая 0. Если у незавершённого предмета нет достижимой цели, общий целевой GPA не рассчитывается.",
        "formula": "GPA = Σ(GPA предмета × кредиты предмета) / Σ(кредиты предметов с оценками)",
    }
