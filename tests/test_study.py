from datetime import datetime, timezone
import pytest

from campuspulse.study import (search_materials, syllabus_candidates, scenario, grade_target,
                              quest_candidates, diagnose, validate_source, scenario_from_message)
from campuspulse.quests import start_quest, answer_quest
from campuspulse.storage import SQLiteStore
from campuspulse.progress import progress

NOW = datetime(2026, 10, 16, 8, tzinfo=timezone.utc)


def material(mid="m1", text="Градиент — вектор частных производных.\nШаг обучения равен 0.01."):
    return {"id": mid, "name": mid + ".txt", "page_count": 1, "pages": [{"page": 1, "text": text}]}


def test_cross_document_quotes_and_differences_are_source_exact():
    docs = [material("m1", "Шаг обучения алгоритма равен 0.01."), material("m2", "Шаг обучения алгоритма равен 0.02.")]
    result = search_materials(docs, "шаг обучения")
    assert len(result["matches"]) == 2
    assert result["possible_differences"]
    assert "не установленное" in result["possible_differences"][0]["note"]
    for s in result["matches"]:
        validate_source(docs, s)
        assert s["quote"] == docs[int(s["material_id"][-1]) - 1]["pages"][0]["text"]
    assert not search_materials(docs, "несуществующее слово")['matches']


def test_syllabus_missing_data_are_not_invented():
    result = syllabus_candidates(material(text="Лабораторная 1: сдать 17 октября 2026 в 13:00\nПроект: сдать 20 октября 2026\nФинальная оценка: экзамен 40%"), now=NOW)
    first, second = result["candidates"][:2]
    assert first["due_at"] == "2026-10-17T13:00:00+05:00"
    assert second["date"] == "2026-10-20" and second["time"] is None and second["due_at"] is None
    assert first["estimated_minutes"] is None and first["course"] == ""
    assert result["grading_rules"][0]["quote"] == "Финальная оценка: экзамен 40%"
    with pytest.raises(ValueError): validate_source([material()], {**first["source"], "quote": "Fake"})


def test_what_if_same_clock_no_mutation_respects_deadline():
    task = {"id": "t", "title": "Lab", "course": "ML", "estimated_minutes": 180, "due_at": "2026-10-16T22:00:00+05:00", "completed": False}
    prefs = {"daily_minutes": 180}
    result = scenario([task], prefs, {"daily_minutes": 60}, NOW)
    assert result["before"]["scheduled_minutes"] == 180 and result["after"]["scheduled_minutes"] == 60
    assert result["delta_minutes"] == -120 and result["after"]["risks"][0]["unscheduled_minutes"] == 120
    assert prefs == {"daily_minutes": 180}
    assert result["changes"]
    assert scenario_from_message("что если 2 часа в день") == {"daily_minutes": 120}
    assert scenario_from_message("осталось 3 дня") == {"days": 3}
    assert scenario_from_message("У меня осталось три дня") == {"days": 3}
    busy = scenario_from_message("Сегодня не успеваю", {"timezone": "Asia/Almaty"}, NOW)["busy"][-1]
    assert busy["end"] == "2026-10-17T00:00:00+05:00"


def grade(**kwargs):
    return {"target": 85, "components": [{"name": "work", "weight": 60, "score": 80, "max_score": 100}, {"name": "final", "weight": 40, "score": None, "max_score": 100}], **kwargs}


def test_grade_decimal_formula_and_impossible_target():
    assert grade_target(grade())["required_score"] == "92.50"
    assert not grade_target(grade(target=95))["achievable"]
    assert grade_target(grade(target=40))["required_score"] == "0.00"
    config = grade(); config["components"][0].update(weight=70, score=83); config["components"][1]["weight"] = 30
    assert grade_target(config)["required_score"] == "89.67"  # rounds upward, not nearest


@pytest.mark.parametrize("change", ["weight", "none", "max", "over"])
def test_grade_rejects_invalid_system(change):
    c = grade()
    if change == "weight": c["components"][0]["weight"] = 50
    if change == "none": c["components"][0]["score"] = None
    if change == "max": c["components"][0]["max_score"] = 0
    if change == "over": c["components"][0]["score"] = 101
    with pytest.raises(ValueError): grade_target(c)


def test_quests_no_repeated_xp_and_no_unapproved_questions(tmp_path):
    store = SQLiteStore(tmp_path / "db")
    m = material(); q = quest_candidates(m)["questions"][0]
    with pytest.raises(ValueError): start_quest(store, "u", m, ["invented"])
    for _ in range(3):
        session = start_quest(store, "u", m, [q["id"]])
        assert "answer" not in session["question"]
        result = answer_quest(store, "u", session["id"], q["id"], "  ГРАДИЕНТ. ")
        assert result["finished"] and result["score_percent"] == 100
        assert answer_quest(store, "u", session["id"], q["id"], "wrong")["score_percent"] == 100
    rewards = store.list("u", "quest_rewards")
    assert len(rewards) == 1 and progress([], quest_rewards=rewards)["xp"] == 10
    assert quest_candidates(material("another"))["questions"][0]["id"] == q["id"]


def test_diagnostics_exact_line_never_execute(tmp_path):
    marker = tmp_path / "should-not-exist"
    assert diagnose(f"open({str(marker)!r}, 'w').write('unsafe')")["syntax_ok"]
    assert not marker.exists()
    assert not diagnose("return 1")["syntax_ok"]
    r = diagnose("x = 2\nif True print(x)\n")
    assert not r["syntax_ok"] and r["issues"][0]["line"] == 2
    assert r["issues"][0]["quote"] == "if True print(x)"
    assert not diagnose('{"x":}', "json", "data.json")["syntax_ok"]
    assert diagnose('{"x": 2}', "json")["syntax_ok"]
    assert diagnose('{"x": "NaN"}', "json")["syntax_ok"]
    nonfinite = diagnose('{\n "x": NaN\n}', "json")["issues"][0]
    assert nonfinite["line"] == 2 and nonfinite["column"] == 7
