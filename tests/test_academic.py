from datetime import datetime, timedelta, timezone
from decimal import Decimal
import random

import pytest
from pydantic import ValidationError

from campuspulse.academic import (
    AcademicSettings, CourseInput, academic_summary, analyze_course,
    default_grade_scale, grade_for_score,
)


NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def course(components=None, **kwargs):
    return {"name": "High Performance Computing", "credits": 5, "components": components or [
        {"name": "Assignment 1", "weight": 10, "score": 75},
        {"name": "Assignment 2", "weight": 10, "score": 80},
        {"name": "Exam 1", "weight": 10},
        {"name": "Exam 2", "weight": 10},
        {"name": "Midterm", "weight": 60},
    ], **kwargs}


def scenario(analysis, target):
    return next(row for row in analysis["scenarios"] if row["target"] == target)


def test_user_example_weighted_grades_and_ceilings():
    result = analyze_course(course(), now=NOW)
    assert result["earned_points"] == 15.5
    assert result["current_average"] == 77.5
    assert result["completed_weight"] == 20
    assert result["max_achievable"] == 95.5
    assert result["active_target"] == 95
    assert result["required_average"] == 99.375
    assert [item["required_score"] for item in result["balanced_plan"]] == [100, 100, 100]
    assert result["projected_total"] == 95.5
    assert [item["conditional_min_score"] for item in result["balanced_plan"]] == [95, 95, 100]
    assert "нельзя" in result["plan_note"]
    assert result["difficulty"] == 5


def test_fallback_recomputes_every_requirement_and_explains_it():
    data = course()
    data["components"][0]["score"] = 60
    result = analyze_course(data, now=NOW)
    assert result["max_achievable"] == 94
    assert result["active_target"] == 90
    assert result["target_lowered"] and result["target_unreachable"]
    assert not scenario(result, 95)["feasible"]
    assert scenario(result, 95)["projected_total"] is None
    assert all(row["required_score"] == 95 for row in result["balanced_plan"])
    assert result["projected_total"] == 90
    assert result["risk"] == "high"


def test_no_fake_goal_if_70_impossible():
    result = analyze_course(course([
        {"name": "Exam", "weight": 80, "score": 20},
        {"name": "Final", "weight": 20},
    ]), now=NOW)
    assert result["max_achievable"] == 36
    assert result["active_target"] is None
    assert result["balanced_plan"] == []
    assert result["remaining_components"][0]["name"] == "Final"
    assert result["risk"] == "critical"


def test_zero_and_missing_are_different_and_no_gpa_without_grades():
    data = course([{"name": "First", "weight": 50}, {"name": "Final", "weight": 50}])
    empty = analyze_course(data, now=NOW)
    assert empty["current_average"] is None and empty["grade"] is None
    assert empty["completed_weight"] == 0
    assert academic_summary([empty])["current_gpa"] is None
    data["components"][0]["score"] = 0
    zero = analyze_course(data, now=NOW)
    assert zero["current_average"] == 0 and zero["grade"]["gpa"] == 0
    assert zero["completed_weight"] == 50
    assert zero["max_achievable"] == 50


def test_normalizes_raw_scores_and_preserves_fractional_maxima():
    result = analyze_course(course([
        {"name": "Quiz", "weight": 20, "score": 15, "max_score": 20},
        {"name": "Project", "weight": 40, "max_score": 1000},
        {"name": "Final", "weight": 40, "max_score": 2.5},
    ], target=90), now=NOW)
    assert result["earned_points"] == 15
    assert result["current_average"] == 75
    assert [row["required_score"] for row in result["balanced_plan"]] == [938, 2.35]
    assert result["projected_total"] >= 90


def test_all_complete_and_already_secured_targets():
    done = analyze_course(course([{"name": "Final", "weight": 100, "score": 93}]), now=NOW)
    assert done["current_average"] == done["earned_points"] == done["max_achievable"] == 93
    assert done["active_target"] == 90
    assert done["risk"] == "complete" and done["priority_score"] == 0
    assert done["balanced_plan"] == []
    assert done["final_grade"]["letter"] == "A-"
    secured = analyze_course(course([
        {"name": "Done", "weight": 90, "score": 100},
        {"name": "Final", "weight": 10},
    ], target=90), now=NOW)
    assert secured["required_average"] == 0
    assert secured["balanced_plan"][0]["required_score"] == 0


def test_user_target_and_configurable_floor():
    result = analyze_course(course(target=92), now=NOW)
    assert result["active_target"] == 92
    poor = course([
        {"name": "Done", "weight": 80, "score": 60},
        {"name": "Final", "weight": 20},
    ])
    assert analyze_course(poor, min_target=70)["active_target"] is None
    assert analyze_course(poor, min_target=60)["active_target"] == 60


def test_personal_target_below_general_floor_is_still_a_valid_goal():
    result = analyze_course(course([{"name": "Final", "weight": 100}], target=60), now=NOW)
    assert result["active_target"] == 60
    assert not result["target_lowered"] and not result["target_unreachable"]
    assert result["balanced_plan"][0]["required_score"] == 60
    assert not any("недостижима" in reason for reason in result["priority_reasons"])


def test_course_policy_warnings_are_preserved_but_not_applied_to_weighted_grade():
    warning = "Automatic Fail при результате аттестации ниже 25%; проверьте условия силлабуса. Калькулятор не применяет это условие автоматически."
    raw = course([{"name": "Final", "weight": 100, "score": 80}], policy_warnings=[warning])
    parsed = CourseInput.model_validate(raw)
    assert parsed.model_dump(mode="json")["policy_warnings"] == [warning]
    result = analyze_course(parsed, now=NOW)
    assert result["policy_warnings"] == [warning]
    assert result["earned_points"] == 80
    assert result["final_grade"]["gpa"] == 3
    assert analyze_course(course(), now=NOW)["policy_warnings"] == []


@pytest.mark.parametrize("warnings", [["x" * 1001], ["x"] * 11, [42]])
def test_course_policy_warnings_reject_oversized_or_invalid_values(warnings):
    with pytest.raises(ValueError):
        CourseInput.model_validate(course(policy_warnings=warnings))


def test_course_policy_warnings_allow_documented_capacity():
    warnings = ["x" * 1000] * 10
    assert analyze_course(course(policy_warnings=warnings), now=NOW)["policy_warnings"] == warnings


def test_precise_personal_goal_is_compared_before_display_rounding():
    target = 94.9999999
    result = analyze_course(course([{"name": "Final", "weight": 100}], target=target), now=NOW)
    assert result["active_target"] == target
    assert not result["target_lowered"] and not result["target_unreachable"]
    assert scenario(result, target)["gpa"] == 3.67
    assert len({s["target"] for s in result["scenarios"]}) == len(result["scenarios"])


def test_personal_gpa_thresholds_and_custom_scale():
    assert grade_for_score(95)["gpa"] == 4
    assert grade_for_score(70)["gpa"] == 2
    assert grade_for_score(65)["gpa"] == 1.67
    assert grade_for_score(69.999999)["gpa"] == 1.67
    custom = [{"min_score": 80, "letter": "Pass", "gpa": 4}, {"min_score": 0, "letter": "Fail", "gpa": 0}]
    result = analyze_course(course(), grade_scale=custom)
    assert result["grade"]["gpa"] == 0
    assert scenario(result, 80)["gpa"] == 4
    defaults = default_grade_scale()
    defaults[0]["gpa"] = 0
    assert default_grade_scale()[0]["gpa"] == 4
    with pytest.raises(ValueError):
        grade_for_score(100.1)


def test_credit_weighted_gpa_excludes_ungraded_courses():
    a = analyze_course(course([{"name": "Final", "weight": 100, "score": 95}], name="A", credits=5))
    b = analyze_course(course([{"name": "Final", "weight": 100, "score": 70}], name="B", credits=10))
    ungraded = analyze_course(course([{"name": "Final", "weight": 100}], name="C", credits=5))
    summary = academic_summary([a, b, ungraded])
    assert summary["current_gpa"] == 2.67  # (4*5 + 2*10) / 15
    assert summary["graded_credits"] == 15
    assert summary["total_credits"] == 20
    assert summary["average_current"] == 78.33
    assert summary["ranked_courses"][0]["name"] == "C"


def test_target_gpa_keeps_final_failed_course_with_zero_in_denominator():
    failed = analyze_course(course([{"name": "Final", "weight": 100, "score": 40}], name="Failed", credits=5))
    future = analyze_course(course([{"name": "Final", "weight": 100}], name="Future", credits=5))
    summary = academic_summary([failed, future])
    assert summary["projected_gpa"] == summary["target_gpa"] == 2
    assert summary["projected_credits"] == 10
    assert summary["unprojected_courses"] == []


def test_target_gpa_cannot_replace_final_high_grade_with_low_personal_goal():
    final = analyze_course(course([{"name": "Final", "weight": 100, "score": 99}], target=70))
    summary = academic_summary([final])
    assert summary["current_gpa"] == summary["target_gpa"] == 4


def test_unfinished_course_without_reachable_goal_does_not_inflate_target_gpa():
    troubled = analyze_course(course([
        {"name": "Failed work", "weight": 90, "score": 40}, {"name": "Final", "weight": 10},
    ], name="Troubled"))
    future = analyze_course(course([{"name": "Final", "weight": 100}], name="Future"))
    summary = academic_summary([troubled, future])
    assert summary["projected_gpa"] is None and summary["target_gpa"] is None
    assert summary["unprojected_courses"] == ["Troubled"]


def test_priorities_follow_risk_credits_difficulty_and_actual_deadlines():
    low = analyze_course(course([{"name": "Final", "weight": 100}], name="Writing", credits=3, difficulty=2), now=NOW)
    high_data = course([
        {"name": "First", "weight": 40, "score": 40},
        {"name": "Final", "weight": 60, "due_at": (NOW + timedelta(hours=12)).isoformat()},
    ], credits=6, difficulty=5)
    high = analyze_course(high_data, now=NOW)
    assert high["priority_score"] > low["priority_score"]
    task_due = (NOW - timedelta(hours=1)).isoformat()
    from_task = analyze_course(course(), tasks=[{"course": "High Performance Computing", "due_at": task_due, "completed": False}], now=NOW)
    assert from_task["nearest_deadline"] == task_due
    assert from_task["evidence"]["priority_inputs"]["urgency"] == 30
    ignored = analyze_course(course(), tasks=[{"course": "Other", "due_at": task_due}, {"course": "High Performance Computing", "due_at": task_due, "completed": True}], now=NOW)
    assert ignored["nearest_deadline"] is None


def test_high_goal_does_not_make_a_healthy_course_high_risk():
    def with_score(score):
        return analyze_course(course([
            {"name": "First", "weight": 40, "score": score},
            {"name": "Final", "weight": 60},
        ], difficulty=3), now=NOW)
    healthy = with_score(95)
    struggling = with_score(75)
    worse = with_score(65)
    assert healthy["required_average"] == 95 and healthy["risk"] == "low"
    assert struggling["active_target"] == 90 and struggling["risk"] == "high"
    assert worse["priority_score"] > struggling["priority_score"] > healthy["priority_score"]
    assert healthy["evidence"]["priority_inputs"]["grade_deficit"] == 0


@pytest.mark.parametrize("patch", [
    {"components": [{"name": "Exam", "weight": 60}]},
    {"components": [{"name": "Exam", "weight": 100, "score": 101}]},
    {"components": [{"name": "Exam", "weight": 100, "score": -1}]},
    {"components": [{"name": "Exam", "weight": 100, "score": float("nan")}]},
    {"components": [{"name": "Exam", "weight": 100, "max_score": 0}]},
    {"components": [{"name": "Exam", "weight": 100, "due_at": "2026-10-21T12:00:00"}]},
    {"components": [{"id": "x", "name": "A", "weight": 50}, {"id": "x", "name": "B", "weight": 50}]},
    {"difficulty": 6}, {"credits": 0}, {"target": 101},
])
def test_invalid_inputs_rejected(patch):
    data = course()
    data.update(patch)
    with pytest.raises(ValidationError):
        CourseInput.model_validate(data)


def test_settings_defaults_and_invalid_scales():
    settings = AcademicSettings()
    assert settings.preferred_target == 95 and settings.min_target == 70
    assert settings.busy == []
    for patch in [
        {"start_hour": 22, "end_hour": 16},
        {"min_target": 96},
        {"timezone": "Nowhere/Nothing"},
        {"busy": [{"start": NOW.isoformat(), "end": (NOW - timedelta(minutes=1)).isoformat()}]},
        {"grade_scale": [{"min_score": 70, "letter": "A", "gpa": 4}]},
        {"grade_scale": [{"min_score": 70, "letter": "A", "gpa": 1}, {"min_score": 0, "letter": "F", "gpa": 4}]},
    ]:
        with pytest.raises(ValidationError):
            AcademicSettings.model_validate(patch)


def test_randomized_balanced_plans_reach_target_without_exceeding_maxima():
    randomizer = random.Random(112)
    for _ in range(80):
        weights = [10, 15, 20, 25, 30]
        components = [{"name": str(i), "weight": weight, "max_score": randomizer.choice([20, 100, 250, 1000]),
                       "score": None} for i, weight in enumerate(weights)]
        for component in components[:randomizer.randint(0, 4)]:
            component["score"] = randomizer.randint(0, int(component["max_score"]))
        result = analyze_course(course(components))
        for row in result["scenarios"]:
            if not row["feasible"]:
                continue
            total = Decimal(str(result["earned_points"]))
            for component in row["balanced_plan"]:
                assert 0 <= component["required_score"] <= component["max_score"]
                total += Decimal(str(component["required_score"])) / Decimal(str(component["max_score"])) * Decimal(str(component["weight"]))
            assert total >= Decimal(str(row["target"])) - Decimal("0.000001")


def test_decimal_weight_tolerance_not_a_license_for_missing_weights():
    result = analyze_course(course([
        {"name": "A", "weight": 33.3333333, "score": 100},
        {"name": "B", "weight": 33.3333333, "score": 100},
        {"name": "C", "weight": 33.3333333, "score": 100},
    ]))
    assert result["earned_points"] == result["current_average"] == 100
    with pytest.raises(ValidationError):
        analyze_course(course([{"name": "A", "weight": 99.99}]))


def test_exact_rational_boundary_does_not_add_an_unnecessary_point():
    # 11/12 * 50 + 7/12 * 50 is EXACTLY 75, not 74.999… or 75.000… .
    data = course([
        {"name": "A", "weight": 50, "score": 11, "max_score": 12},
        {"name": "B", "weight": 50, "max_score": 12},
    ], target=75)
    result = analyze_course(data)
    assert result["balanced_plan"][0]["required_score"] == 7
    assert result["balanced_plan"][0]["conditional_min_score"] == 7
    assert result["projected_total"] == 75
    data["components"][1]["score"] = 7
    final = analyze_course(data)
    assert final["current_average"] == 75
    assert final["grade"]["gpa"] == 2.67


def test_arbitrary_fractional_maximum_never_rounded_past_its_maximum():
    result = analyze_course(course([
        {"name": "A", "weight": 20, "score": 75},
        {"name": "B", "weight": 80, "max_score": 2.3456789},
    ], target=95))
    assert result["balanced_plan"][0]["required_score"] == 2.3456789
