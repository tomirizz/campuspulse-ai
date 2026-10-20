"""Compact tool observations for the model, without changing audit evidence.

Only the two high-volume academic tools have a projection. The original tool
result remains the source for the UI, evidence renderer and public action trace.
Values below are copied verbatim; only list counts are derived. In particular,
the model does not receive the repeated per-target grade scenarios or per-day
copies of sessions. Truncation is explicit and must not imply full coverage.
"""
from copy import deepcopy


COURSE_LIMIT = 12
ASSESSMENT_LIMIT = 12
SESSION_LIMIT = 12
RISK_LIMIT = 8

_COURSE_FIELDS = (
    "id", "name", "credits", "difficulty", "target", "current_average",
    "earned_points", "completed_weight", "remaining_weight", "max_achievable",
    "active_target", "required_average", "projected_total", "target_lowered",
    "target_unreachable", "risk", "priority_score", "priority_reasons",
    "nearest_deadline", "plan_note",
)
_ASSESSMENT_FIELDS = (
    "id", "name", "weight", "required_score", "required_percent", "max_score", "due_at",
)
_SUMMARY_FIELDS = (
    "course_count", "total_credits", "graded_credits", "graded_courses",
    "current_gpa", "projected_gpa", "target_gpa", "average_current", "at_risk",
    "gpa_note", "formula",
)
_SESSION_FIELDS = ("title", "course", "start", "end", "minutes", "due_at", "reason")
_RISK_FIELDS = ("title", "course", "reason", "unscheduled_minutes")
_ALLOCATION_FIELDS = (
    "course", "minutes", "scheduled_minutes", "required_minutes", "unscheduled_minutes",
    "share_percent", "priority_score", "credits", "difficulty", "risk", "reasons",
)


def _pick(value, fields):
    return {key: deepcopy(value[key]) for key in fields if key in value}


def _rows(value, fields, limit):
    return [_pick(row, fields) for row in value[:limit]]


def _has_rows(result, key):
    return key not in result or (
        isinstance(result[key], list) and all(isinstance(row, dict) for row in result[key])
    )


def _overview(result):
    # Unexpected shapes are left intact instead of silently dropping data.
    if not _has_rows(result, "courses") or not isinstance(result.get("summary", {}), dict):
        return deepcopy(result)
    courses = result.get("courses", [])
    if any(not _has_rows(course, "balanced_plan") for course in courses):
        return deepcopy(result)
    compact = {"courses": [], "course_count": len(courses),
               "courses_omitted_count": max(0, len(courses) - COURSE_LIMIT)}
    for course in courses[:COURSE_LIMIT]:
        row = _pick(course, _COURSE_FIELDS)
        if "balanced_plan" in course:
            plan = course["balanced_plan"]
            row.update(balanced_plan=_rows(plan, _ASSESSMENT_FIELDS, ASSESSMENT_LIMIT),
                       balanced_plan_count=len(plan),
                       balanced_plan_omitted_count=max(0, len(plan) - ASSESSMENT_LIMIT))
        compact["courses"].append(row)
    if "summary" in result:
        compact["summary"] = _pick(result["summary"], _SUMMARY_FIELDS)
        # At-risk names are useful, but are not another full ranked course list.
        names = result["summary"].get("at_risk_names")
        if isinstance(names, list):
            compact["summary"]["at_risk_names"] = deepcopy(names[:COURSE_LIMIT])
            compact["summary"]["at_risk_names_omitted_count"] = max(0, len(names) - COURSE_LIMIT)
    notes = result.get("schedule_notes")
    if isinstance(notes, list):
        compact["schedule_notes"] = deepcopy(notes[:RISK_LIMIT])
        compact["schedule_notes_omitted_count"] = max(0, len(notes) - RISK_LIMIT)
    return compact


def _plan(result):
    if any(not _has_rows(result, key) for key in ("sessions", "risks", "course_allocations")):
        return deepcopy(result)
    compact = _pick(result, ("scheduled_minutes", "timezone", "generated_at", "policy", "disclaimer"))
    for key, fields, limit, count in (
        ("sessions", _SESSION_FIELDS, SESSION_LIMIT, "session_count"),
        ("risks", _RISK_FIELDS, RISK_LIMIT, "risk_count"),
        ("course_allocations", _ALLOCATION_FIELDS, COURSE_LIMIT, "course_allocation_count"),
    ):
        if key in result:
            rows = result[key]
            compact[key] = _rows(rows, fields, limit)
            compact[count] = len(rows)
            compact[key + "_omitted_count"] = max(0, len(rows) - limit)
    if isinstance(result.get("days"), list):
        compact["day_count"] = len(result["days"])
    return compact


def model_observation(name: str, result: dict) -> dict:
    """Return a detached, JSON-compatible view; never mutate the full result.

    Unknown tools and tool errors pass through unchanged in value. No grade,
    score, deadline, study minute or explanatory text is generated here.
    ``balanced_plan`` deliberately excludes conditional minima: they cannot be
    combined into one jointly achievable plan.
    """
    if not isinstance(result, dict) or "error" in result:
        return deepcopy(result)
    if name == "academic_overview":
        return _overview(result)
    if name == "academic_plan":
        return _plan(result)
    return deepcopy(result)
