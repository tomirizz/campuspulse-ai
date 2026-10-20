from copy import deepcopy
from datetime import datetime
import json

import pytest

from campuspulse.academic import academic_summary, analyze_course
from campuspulse.academic_planner import build_study_plan
from campuspulse.agent_observations import model_observation


NOW = datetime.fromisoformat("2026-10-20T15:00:00+05:00")


def demo_courses():
    courses = []
    for index, name in enumerate(("High Performance Computing (HPC)", "Statistics", "Academic Writing", "Mathematics")):
        raw = {"id": "course-" + str(index), "name": name, "credits": 5, "target": 95,
               "components": [{"id": "a-" + str(item), "name": title, "weight": weight,
                               "score": score, "source_quote": "Observed syllabus row: " + title,
                               "estimated_minutes": 240}
                              for item, (title, weight, score) in enumerate((
                                  ("Assignment 1", 12, 75), ("Mid Term", 18, 80),
                                  ("Assignment 2", 6, None), ("Assignment 3", 6, None),
                                  ("End Term", 18, None), ("Final exam", 40, None)))]}
        courses.append(analyze_course(raw, now=NOW))
    return courses


def byte_size(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def test_real_four_course_overview_is_much_smaller_without_changing_calculations():
    courses = demo_courses()
    original = {"courses": courses, "summary": academic_summary(courses),
                "why": {"inputs": courses, "formula": "already calculated"},
                "schedule_notes": ["Final exam date was matched to its course"]}
    before = deepcopy(original)
    compact = model_observation("academic_overview", original)
    assert byte_size(compact) < byte_size(original) * .25
    assert len(compact["courses"]) == 4 and compact["courses_omitted_count"] == 0
    assert compact["summary"]["current_gpa"] == original["summary"]["current_gpa"]
    assert "ranked_courses" not in compact["summary"] and "why" not in compact
    for actual, saved in zip(compact["courses"], courses):
        for key in ("current_average", "earned_points", "remaining_weight", "active_target", "required_average", "priority_score"):
            assert actual[key] == saved[key]
        assert actual["priority_reasons"] == saved["priority_reasons"]
        assert "scenarios" not in actual and "components" not in actual
        assert "plan_note" in actual
        for assessment, full in zip(actual["balanced_plan"], saved["balanced_plan"]):
            assert assessment["name"] == full["name"]
            assert assessment["required_score"] == full["required_score"]
            assert assessment["required_percent"] == full["required_percent"]
            assert "conditional_min_score" not in assessment and "source_quote" not in assessment
    assert original == before
    compact["courses"][0]["priority_reasons"].append("model-only copy")
    assert original == before


def test_real_four_course_plan_preserves_totals_and_risks_but_not_day_duplicates():
    full = build_study_plan(demo_courses(), [], {}, now=NOW, days=7)
    full["why"] = {"inputs": full["days"]}
    before = deepcopy(full)
    compact = model_observation("academic_plan", full)
    assert byte_size(compact) < byte_size(full) * .45
    assert compact["scheduled_minutes"] == full["scheduled_minutes"]
    assert compact["session_count"] == len(full["sessions"])
    assert compact["risk_count"] == len(full["risks"])
    assert compact["day_count"] == 7
    assert len(compact["sessions"]) == 12 and compact["sessions_omitted_count"] > 0
    assert "days" not in compact and "why" not in compact and "defaults" not in compact
    assert compact["disclaimer"] == full["disclaimer"]
    assert compact["policy"] == full["policy"]
    for row, saved in zip(compact["sessions"], full["sessions"]):
        assert row == {key: saved[key] for key in ("title", "course", "start", "end", "minutes", "due_at", "reason")}
    assert full == before
    compact["course_allocations"][0]["reasons"].append("detached")
    assert full == before


def test_list_limits_have_exact_omission_counts_and_keep_original_order():
    courses = [{"id": str(index), "name": f"Course {index}", "current_average": None,
                "balanced_plan": [{"name": f"Exam {n}", "weight": 5, "required_score": None,
                                   "max_score": 100, "conditional_min_score": 0} for n in range(20)]}
               for index in range(15)]
    full = {"courses": courses, "summary": {"course_count": 15, "at_risk_names": [c["name"] for c in courses]},
            "schedule_notes": ["Note " + str(index) for index in range(10)]}
    compact = model_observation("academic_overview", full)
    assert compact["course_count"] == 15 and compact["courses_omitted_count"] == 3
    assert [row["id"] for row in compact["courses"]] == [str(index) for index in range(12)]
    assert compact["courses"][0]["current_average"] is None
    assert compact["courses"][0]["balanced_plan_count"] == 20
    assert compact["courses"][0]["balanced_plan_omitted_count"] == 8
    assert len(compact["courses"][0]["balanced_plan"]) == 12
    assert compact["summary"]["at_risk_names_omitted_count"] == 3
    assert compact["schedule_notes_omitted_count"] == 2

    plan = {"sessions": [{"title": str(n), "minutes": 50} for n in range(30)],
            "risks": [{"reason": str(n), "unscheduled_minutes": 70} for n in range(15)],
            "course_allocations": [{"course": str(n)} for n in range(14)], "scheduled_minutes": 1500}
    compact_plan = model_observation("academic_plan", plan)
    assert compact_plan["session_count"] == 30 and compact_plan["sessions_omitted_count"] == 18
    assert compact_plan["risk_count"] == 15 and compact_plan["risks_omitted_count"] == 7
    assert compact_plan["course_allocation_count"] == 14 and compact_plan["course_allocations_omitted_count"] == 2
    assert compact_plan["scheduled_minutes"] == 1500  # Not the partial preview's sum.
    assert compact_plan["risks"] == plan["risks"][:8]


@pytest.mark.parametrize("name,value", [
    ("current_time", {"now": "observed", "nested": [1, {"x": 2}]}),
    ("academic_overview", {"error": "No data", "details": [{"why": "preserve"}]}),
    ("academic_plan", {"error": None, "sessions": []}),
    ("academic_overview", {"courses": "unexpected"}),
    ("academic_overview", {"courses": [{"balanced_plan": "unexpected"}]}),
    ("academic_plan", {"sessions": ["unexpected"]}),
])
def test_unknown_errors_and_unexpected_shapes_pass_through_without_aliases(name, value):
    compact = model_observation(name, value)
    assert compact == value and compact is not value
    assert json.loads(json.dumps(compact)) == value


def test_empty_and_missing_values_are_not_fabricated():
    compact = model_observation("academic_overview", {"courses": [{"name": "New course"}]})
    assert compact["courses"] == [{"name": "New course"}]
    assert "summary" not in compact and "earned_points" not in compact["courses"][0]
    plan = model_observation("academic_plan", {"sessions": [], "risks": [], "scheduled_minutes": 0})
    assert plan["scheduled_minutes"] == 0 and plan["session_count"] == 0 and plan["risk_count"] == 0
    assert "policy" not in plan and "disclaimer" not in plan
