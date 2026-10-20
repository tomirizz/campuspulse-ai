from datetime import datetime, timedelta
import random

from campuspulse.academic_planner import build_study_plan


NOW = datetime.fromisoformat("2026-10-20T15:52:00+05:00")


def course(name="Maths", credits=5, difficulty=3, risk="medium", minutes=1200, **extra):
    return {"id": name, "name": name, "credits": credits, "difficulty": difficulty,
            "risk": risk, "priority_score": 50, "remaining_weight": 100,
            "components": [{"id": name + "-exam", "name": "Exam", "weight": 100,
                            "score": None, "estimated_minutes": minutes}], **extra}


def test_defaults_and_non_overlapping_work_breaks():
    result = build_study_plan([course()], [], {}, now=NOW, days=1)
    assert result["scheduled_minutes"] == 180
    assert result["defaults"]["session_minutes"] == 50
    assert result["sessions"][0]["start"] == "2026-10-20T16:00:00+05:00"
    assert result["sessions"][0]["due_at"] is None  # A planning horizon is not an observed deadline.
    for first, second in zip(result["sessions"], result["sessions"][1:]):
        assert datetime.fromisoformat(second["start"]) - datetime.fromisoformat(first["end"]) >= timedelta(minutes=10)


def test_no_past_busy_or_post_deadline_sessions():
    now = NOW.replace(hour=17, minute=7)
    prefs = {"busy": [{"start": "2026-10-20T18:00:00+05:00", "end": "2026-10-20T19:00:00+05:00"}]}
    settings = {"busy": [{"start": "2026-10-20T20:00:00+05:00", "end": "2026-10-20T22:00:00+05:00"}]}
    task = {"id": "urgent", "title": "Project", "course": "Maths", "estimated_minutes": 300,
            "due_at": "2026-10-20T19:30:00+05:00"}
    result = build_study_plan([], [task], prefs, settings=settings, now=now, days=1)
    for session in result["sessions"]:
        start, end = datetime.fromisoformat(session["start"]), datetime.fromisoformat(session["end"])
        assert now <= start < end <= datetime.fromisoformat(task["due_at"])
        assert end <= now.replace(hour=18, minute=0) or start >= now.replace(hour=19, minute=0)
    assert result["risks"]


def test_risk_and_credits_drive_fair_allocation():
    courses = [course("Hard", credits=6, difficulty=5, risk="critical"),
               course("Easy", credits=2, difficulty=2, risk="low")]
    result = build_study_plan(courses, [], {}, now=NOW, days=3)
    allocations = {a["course"]: a["minutes"] for a in result["course_allocations"]}
    assert allocations["Hard"] > allocations["Easy"] > 0


def test_urgent_deadline_moves_task_early():
    tasks = [{"id": "urgent", "title": "Urgent", "course": "A", "estimated_minutes": 50, "due_at": "2026-10-20T17:00:00+05:00"},
             {"id": "later", "title": "Later", "course": "B", "estimated_minutes": 50, "due_at": "2026-10-25T17:00:00+05:00"}]
    result = build_study_plan([], tasks, {}, now=NOW, days=1)
    assert result["sessions"][0]["task_id"] == "urgent"
    assert result["scheduled_minutes"] == 100


def test_completed_courses_and_tasks_need_no_time():
    completed = course(remaining_weight=0)
    completed["components"][0]["score"] = 90
    result = build_study_plan([completed], [{"id": "done", "course": "Done", "completed": True}], {}, now=NOW)
    assert result["scheduled_minutes"] == 0
    assert not result["sessions"]


def test_same_names_have_independent_course_ids_and_no_overwritten_work():
    first = course("Maths", id="semester-one", minutes=60)
    second = course("Maths", id="semester-two", minutes=90)
    result = build_study_plan([first, second], [], {}, now=NOW, days=2)
    assert result["scheduled_minutes"] == 150
    assert {s["course_id"] for s in result["sessions"]} == {"semester-one", "semester-two"}
    assert {s["course"] for s in result["sessions"]} == {"Maths"}
    assert {a["course_id"]: a["minutes"] for a in result["course_allocations"]} == {"semester-one": 60, "semester-two": 90}


def test_same_named_complete_course_does_not_hide_unfinished_course():
    opened = course("Maths", id="open", minutes=60)
    completed = course("Maths", id="complete", remaining_weight=0)
    completed["components"][0]["score"] = 100
    result = build_study_plan([opened, completed], [], {}, now=NOW, days=1)
    assert result["scheduled_minutes"] == 60
    assert {s["course_id"] for s in result["sessions"]} == {"open"}
    assert len(result["course_allocations"]) == 2


def test_ambiguous_legacy_task_name_warns_instead_of_picking_wrong_course():
    courses = [course("Maths", id="one", minutes=30), course("Maths", id="two", minutes=30)]
    task = {"id": "legacy", "title": "Exam", "course": "Maths", "estimated_minutes": 50}
    result = build_study_plan(courses, [task], {}, now=NOW, days=1)
    assert result["scheduled_minutes"] == 60
    assert {s["course_id"] for s in result["sessions"]} == {"one", "two"}
    assert any(r.get("task_id") == "legacy" and "Несколько предметов" in r["reason"] for r in result["risks"])


def test_explicit_course_id_resolves_task_when_course_names_match():
    courses = [course("Maths", id="one", minutes=30), course("Maths", id="two", minutes=30)]
    task = {"id": "explicit", "title": "Exam", "course": "Maths", "course_id": "two", "estimated_minutes": 50}
    result = build_study_plan(courses, [task], {}, now=NOW, days=1)
    allocations = {a["course_id"]: a["minutes"] for a in result["course_allocations"]}
    assert allocations == {"one": 30, "two": 50}
    assert not result["risks"]


def test_overdue_deadline_gets_explicit_risk():
    task = {"id": "late", "title": "Overdue", "course": "A", "estimated_minutes": 80, "due_at": "2026-10-19T19:00:00+05:00"}
    result = build_study_plan([], [task], {}, now=NOW)
    assert not result["sessions"]
    assert result["risks"][0]["unscheduled_minutes"] == 80


def test_assessment_task_not_counted_twice():
    task = {"id": "my-task", "title": "Exam", "course": "Maths", "estimated_minutes": 50,
            "due_at": "2026-10-21T18:00:00+05:00"}
    result = build_study_plan([course()], [task], {}, now=NOW)
    assert result["scheduled_minutes"] == 50
    assert result["course_allocations"][0]["required_minutes"] == 50


def test_all_busy_returns_zero_and_honest_shortage():
    result = build_study_plan([course(minutes=120)], [], {"busy": [
        {"start": "2026-10-20T16:00:00+05:00", "end": "2026-10-20T22:00:00+05:00"}]}, now=NOW, days=1)
    assert result["scheduled_minutes"] == 0
    assert result["days"][0]["free_minutes"] == 0
    assert result["risks"][0]["unscheduled_minutes"] == 120


def test_duplicate_busy_imports_are_merged_and_new_settings_limits_work():
    block = {"start": "2026-10-20T16:00:00+05:00", "end": "2026-10-20T17:00:00+05:00"}
    result = build_study_plan([course()], [], {"daily_minutes": 15, "busy": [block]},
                              settings={"busy": [block], "imported_busy": [block]}, now=NOW, days=1)
    assert result["scheduled_minutes"] == 15
    assert len(result["days"][0]["busy"]) == 1
    assert result["days"][0]["free_minutes"] == 300


def test_remaining_assessments_are_balanced_without_micro_sessions():
    example = course(minutes=120)
    example["components"] = [{"id": f"exam-{index}", "name": f"Exam {index}",
                               "score": None, "weight": 25, "estimated_minutes": 120}
                              for index in range(4)]
    result = build_study_plan([example], [], {}, now=NOW, days=7)
    assert result["scheduled_minutes"] == 480
    assert not result["risks"]
    assert all(25 <= session["minutes"] <= 50 for session in result["sessions"])


def test_fifty_five_minute_task_becomes_two_useful_chunks():
    result = build_study_plan([course(minutes=55)], [], {}, now=NOW, days=1)
    assert sorted(session["minutes"] for session in result["sessions"]) == [27, 28]
    assert result["scheduled_minutes"] == 55
    assert not result["risks"]


def test_short_actual_tasks_and_tight_free_intervals_remain_usable():
    task = {"id": "short", "title": "Quiz review", "course": "A", "estimated_minutes": 15,
            "due_at": "2026-10-20T16:20:00+05:00"}
    result = build_study_plan([], [task], {}, now=NOW, days=1)
    assert result["scheduled_minutes"] == 15
    assert not result["risks"]
    assert "Короткий блок" in result["sessions"][0]["reason"]


def test_many_irregular_estimates_do_not_stall_behind_orphan_fragments():
    rng = random.Random(12)
    tasks = [{"id": str(i), "title": str(i), "course": str(i % 3),
              "estimated_minutes": rng.randint(15, 240), "due_at": "2026-11-02T22:00:00+05:00"}
             for i in range(60)]
    result = build_study_plan([], tasks, {"daily_minutes": 600, "start_hour": 8, "end_hour": 23},
                              now=NOW.replace(hour=15, minute=0), days=14)
    assert result["scheduled_minutes"] == sum(task["estimated_minutes"] for task in tasks)
    assert not result["risks"]
    assert all(session["minutes"] >= 15 for session in result["sessions"])


def test_randomized_total_capacity_and_deadline_invariants():
    rng = random.Random(119)
    tasks = [{"id": str(i), "title": "Task " + str(i), "course": "Course " + str(i % 4),
              "estimated_minutes": rng.randint(15, 240),
              "due_at": (NOW + timedelta(days=rng.randint(1, 6))).isoformat()} for i in range(24)]
    result = build_study_plan([], tasks, {"daily_minutes": 180}, now=NOW, days=7)
    by_id = {t["id"]: t for t in tasks}
    for session in result["sessions"]:
        start, end = datetime.fromisoformat(session["start"]), datetime.fromisoformat(session["end"])
        assert NOW <= start < end <= datetime.fromisoformat(by_id[session["task_id"]]["due_at"])
        assert 0 < session["minutes"] <= 60
    assert all(day["scheduled_minutes"] <= 180 for day in result["days"])
    assert sum(t["estimated_minutes"] for t in tasks) == result["scheduled_minutes"] + sum(r["unscheduled_minutes"] for r in result["risks"])
    for first, second in zip(result["sessions"], result["sessions"][1:]):
        assert datetime.fromisoformat(first["end"]) <= datetime.fromisoformat(second["start"])
