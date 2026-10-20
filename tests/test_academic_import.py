from datetime import datetime

import pytest

from campuspulse.academic_import import EXAMPLE_SYLLABUS_TEXT, parse_schedule, parse_syllabus


POINT_SYLLABUS = r"""**Final Grade Calculation Formula**
\(\text{Final\ Grade}=0.3\times \text{1st\ Attestation}+0.3\times \text{2nd\ Attestation}+0.4\times \text{Final\ Exam}\)
**1. 1st Attestation (Mid-term, Weeks 1–5)**
- **Weight:** Max **30 points** (30% of the final grade)
- **Components:**
  - **MCQ Test 1** (Week 4, based on Lectures 1–3, 50 questions) — **18 points**
  - **Team Project 1** (Report and oral defense, Week 5) — **12 points**
**2. 2nd Attestation (End-term, Weeks 6–10)**
- **Weight:** Max **30 points** (30% of the final grade)
  - **Team Project 2** (Report and oral defense, Week 8) — **12 points**
  - **MCQ Test 2** (Week 9, based on Lectures 4–8, 50 questions) — **18 points**
**3. Final Exam (Week 10)**
- **Weight:** Max **40 points** (40% of the final grade)
  - **Final Team Project** (Report and oral defense, Week 10) — **40 points**
**Important Academic Policies**
- **Automatic Fail Rule:** If you receive **less than a 25% score** on either the 1st or 2nd Attestation (less than 7.5 points out of 30), you will automatically **fail the course** and will need to retake it.
- **Late Submissions:** No late submissions are allowed. Missing a deadline results in **0 points**.
"""


WEEKLY_SCHEDULE = """**Monday (Понедельник)**
- **15:00-15:50** — Statistics and Data Science 2 (Python) | lecture | **C1.3.234L**
- **16:00-16:50** — Statistics and Data Science 2 (Python) | lecture | **C1.3.234L**
**Tuesday (Вторник)**
- **14:00-14:50** — Statistics and Data Science 2 (Python) | practice | **IEC-307**
- **16:00-16:50** — Academic Writing | practice | **C1.1.235P**
- **17:00-17:50** — Academic Writing | practice | **C1.1.235P**
- **18:00-18:50** — Computational Mathematics | practice | **C1.1.235P**
- **19:00-19:50** — Computational Mathematics | practice | **C1.1.235P**
**Wednesday (Среда)**
- **13:05-13:55** — Introduction to Optimization | lecture | **C1.3.234L**
- **14:00-14:50** — Introduction to Optimization | lecture | **C1.3.234L**
- **15:00-15:50** — Introduction to Optimization | practice | **C1.3.322**
- **16:00-16:50** — Computational Linear Algebra and Iterative Methods | practice | **C1.3.318**
- **17:00-17:50** — Computational Linear Algebra and Iterative Methods | practice | **C1.3.318**
**Thursday (Четверг)**
- **12:00-12:50** — Computational Linear Algebra and Iterative Methods | lecture | **C1.1.251L**
- **13:05-13:55** — Computational Linear Algebra and Iterative Methods | lecture | **C1.1.251L**
- **14:00-14:50** — Statistics and Data Science 2 (Python) | practice | **C1.1.361K**
- **15:00-15:50** — Statistics and Data Science 2 (Python) | practice | **C1.1.361K**
- **17:00-17:50** — Introduction to Optimization | practice | **C1.3.254L**
- **18:00-18:50** — Introduction to Optimization | practice | **C1.3.254L**
**Friday (Пятница)**
- **15:00-15:50** — Academic Writing | practice | **C1.1.234P**
- **17:00-17:50** — Computational Linear Algebra and Iterative Methods | practice | **C1.3.318**
- **18:00-18:50** — Computational Mathematics | practice | **C1.1.235P**
"""


def test_nested_weights_are_global_and_subtotals_not_double_counted():
    result = parse_syllabus(EXAMPLE_SYLLABUS_TEXT)
    course = result["course"]
    assert course["name"] == "High Performance Computing (HPC)"
    assert course["credits"] == 5
    assert [row["weight"] for row in course["components"]] == [12, 18, 6, 6, 18, 40]
    assert sum(row["weight"] for row in course["components"]) == 100
    assert all(row["score"] is None and row["max_score"] == 100 for row in course["components"])
    assert all(row["source_quote"] for row in course["components"])
    assert not result["warnings"]


def test_observed_course_title_takes_precedence_over_upload_filename():
    result = parse_syllabus(EXAMPLE_SYLLABUS_TEXT, name="syllabus.pdf")
    assert result["course"]["name"] == "High Performance Computing (HPC)"


def test_pdf_pages_and_decimal_comma_formula():
    text = EXAMPLE_SYLLABUS_TEXT.replace("0.3", "0,3").replace("0.4", "0,4")
    text = text.replace("1st attestation", "1st\nattestation").replace("2nd attestation", "2nd\nattestation")
    result = parse_syllabus([{"text": text[:150]}, {"text": text[150:]}])
    assert sum(r["weight"] for r in result["course"]["components"]) == 100


def test_single_assignment_inherits_observed_aggregate_only():
    text = EXAMPLE_SYLLABUS_TEXT.replace("assignment 1: 40", "assignment 1")
    result = parse_syllabus(text)
    assert result["course"]["components"][0]["weight"] == 12


def test_detached_table_values():
    text = EXAMPLE_SYLLABUS_TEXT.replace("assignment 2: 20", "assignment 2\n20").replace("Mid Term: 60", "Mid Term\n60")
    result = parse_syllabus(text)
    assert [r["weight"] for r in result["course"]["components"]] == [12, 18, 6, 6, 18, 40]


def test_unknown_child_weights_stay_as_aggregate_not_invented():
    text = EXAMPLE_SYLLABUS_TEXT.replace("assignment 2: 20", "assignment 2").replace("assignment 3: 20", "assignment 3")
    result = parse_syllabus(text)
    components = result["course"]["components"]
    second = [r for r in components if "2nd" in r["name"]]
    assert sorted(r["weight"] for r in second) == [12, 18]
    assert result["warnings"]


def test_inconsistent_child_sum_is_not_silently_normalized():
    result = parse_syllabus(EXAMPLE_SYLLABUS_TEXT.replace("assignment 3: 20", "assignment 3: 30"))
    assert result["warnings"]
    assert sum(r["weight"] for r in result["course"]["components"]) != 100


def test_missing_outer_formula_never_treats_local_points_as_global():
    result = parse_syllabus(EXAMPLE_SYLLABUS_TEXT.split("Total:")[0])
    assert not result["course"]["components"]
    assert result["warnings"]


def test_flat_percentages_and_explicit_name():
    result = parse_syllabus("Assignment 1: 10%\nAssignment 2: 10%\nMidterm: 60%\nFinal exam: 20%", name="Physics")
    assert result["course"]["name"] == "Physics"
    assert [r["weight"] for r in result["course"]["components"]] == [10, 10, 60, 20]
    assert result["course"]["credits"] is None


def test_russian_hierarchical_sections():
    text = EXAMPLE_SYLLABUS_TEXT.replace("Course title", "Название дисциплины").replace("Number of credits", "Количество кредитов")
    text = text.replace("1st attestation", "1 аттестация").replace("2nd attestation", "2 аттестация")
    text = text.replace("1st Att", "РК1").replace("2nd Att", "РК2")
    assert [r["weight"] for r in parse_syllabus(text)["course"]["components"]] == [12, 18, 6, 6, 18, 40]


def test_unknown_data_bounded_and_not_invented():
    result = parse_syllabus("No grading scheme here" * 20_000)
    assert len(result["source_text"]) <= 150_000
    assert result["course"]["credits"] is None
    assert not result["course"]["components"]
    assert result["confidence"] <= .4


def test_actual_clipped_screenshot_ocr_stays_incomplete():
    text = """4. Student Performance Evaluation System for the Course
Period Assignments Number Total
of oints
Assignments* * 40 100
attestation assignment I 60
Mid Term
2nd Assignments* * 40 100
attestation assignment 2 20
assignment 3 20
End Term 60
Final exam* Quiz 100
Total 0,3 * ISt Att + * 2nd Att+ 100"""
    result = parse_syllabus(text)
    assert result["warnings"]
    assert sum(row["weight"] for row in result["course"]["components"]) != 100


def test_explicit_percentage_wins_over_unlabelled_score_number():
    result = parse_syllabus("Assignment 1 score 75 weight 10%\nFinal exam 90%", name="Maths")
    assert [row["weight"] for row in result["course"]["components"]] == [10, 90]


def test_dated_exam_schedule_and_merged_date_cell():
    text = """2026
25.05 Mo. 15:00-16:00 Computational Mathematics C1.1.251L exam Teacher
26.05 Tu. 09:00-10:00 Introduction to Optimization C1.3.361L exam Teacher
06.06 Sa. 10:00-11:00 Computational Linear Algebra and Iterative methods C1.1.353K examfx Teacher
13:00-14:00 Stochastic Processes C1.1.228P examfx Teacher
"""
    result = parse_schedule(text)
    assert len(result["busy"]) == 4
    assert len(result["exams"]) == 4
    assert result["busy"][0]["title"] == "Computational Mathematics"
    assert result["busy"][0]["start"] == "2026-05-25T15:00:00+05:00"
    assert result["busy"][-1]["start"] == "2026-06-06T13:00:00+05:00"
    assert result["exams"][0]["assessment_kind"] == "exam"
    assert result["exams"][-1]["assessment_kind"] == "final"
    assert result["exams"][-1]["source_quote"] == "13:00-14:00 Stochastic Processes C1.1.228P examfx Teacher"
    assert result["recurring"] is False


def test_schedule_does_not_turn_weekdays_into_invented_dates():
    result = parse_schedule("Monday 15:00-16:00 Mathematics", year=2026)
    assert not result["busy"]
    assert result["warnings"]


def test_schedule_rejects_invalid_dates_and_negative_ranges():
    result = parse_schedule("31.02 10:00-11:00 Maths\n25.05 16:00-15:00 Physics", year=2026)
    assert not result["busy"]
    assert len(result["warnings"]) >= 2


def test_schedule_explicit_assessment_kinds_do_not_assume_every_exam_is_final():
    text = """25.05 10:00-11:00 Mathematics | exam
26.05 10:00-11:00 Mathematics | examf
27.05 10:00-11:00 Mathematics | Midterm
28.05 10:00-11:00 Mathematics | End Term"""
    result = parse_schedule(text, year=2026)
    assert [exam["assessment_kind"] for exam in result["exams"]] == ["exam", "final", "midterm", "endterm"]


def test_schedule_keeps_exact_original_punctuation_in_source_quote():
    text = "25.05 10:00–11:00 Mathematics | examf"
    result = parse_schedule(text, year=2026)
    assert result["exams"][0]["source_quote"] == text


def test_actual_markdown_points_are_global_not_multiplied_by_outer_weight_twice():
    result = parse_syllabus(POINT_SYLLABUS)
    assert [row["weight"] for row in result["course"]["components"]] == [18, 12, 12, 18, 40]
    assert [row["name"] for row in result["course"]["components"]] == ["MCQ Test 1", "Team Project 1", "Team Project 2", "MCQ Test 2", "Final Team Project"]
    assert all(row["score"] is None and row["max_score"] == row["weight"] and row["source_quote"] for row in result["course"]["components"])
    assert result["course"]["name"] == "Новый предмет" and result["course"]["credits"] is None
    assert any("Название" in warning for warning in result["warnings"])
    assert result["confidence"] >= .8  # Complete math needs no quota-limited AI.
    assert len(result["policy_warnings"]) == 2
    assert "7.5" in result["policy_warnings"][0] and "25%" in result["policy_warnings"][0]
    assert "не применяет" in result["policy_warnings"][0]


def test_filename_is_only_a_suggested_name_and_explicit_group_denominators_are_used():
    result = parse_syllabus(POINT_SYLLABUS.replace("Max **30 points**", "Max **60 points**", 1)
                            .replace("**18 points**", "**36 points**", 1)
                            .replace("**12 points**", "**24 points**", 1), name="Project_Management_0001.pdf")
    assert result["course"]["name"] == "Project_Management_0001"
    assert any("имени файла" in warning for warning in result["warnings"])
    assert [row["weight"] for row in result["course"]["components"]] == [18, 12, 12, 18, 40]


@pytest.mark.parametrize("text", [
    POINT_SYLLABUS.replace("**18 points**", "**17 points**", 1),
    POINT_SYLLABUS.replace("0.3\\times \\text{1st", "0.2\\times \\text{1st"),
])
def test_incomplete_or_contradictory_explicit_group_points_are_not_normalized(text):
    result = parse_syllabus(text)
    assert sum(row["weight"] for row in result["course"]["components"]) != 100
    assert result["confidence"] <= .4 and result["warnings"]


def test_exact_weekly_markdown_schedule_produces_21_rules_252_dated_intervals_and_five_courses():
    result = parse_schedule(WEEKLY_SCHEDULE, anchor_date="2026-10-19")
    assert result["recurring"] is True and result["weekly_count"] == 21
    assert len(result["busy"]) == 252 and result["weeks"] == 12
    assert result["week_start"] == "2026-10-19" and result["coverage_end"] == "2027-01-10"
    assert [sum(row["weekday"] == day for row in result["weekly_rules"]) for day in range(5)] == [2, 5, 5, 6, 3]
    assert len(result["courses"]) == 5 and "Statistics and Data Science 2 (Python)" in result["courses"]
    assert result["weekly_rules"][0]["room"] == "C1.3.234L"
    assert result["weekly_rules"][0]["kind"] == "lecture"
    assert result["busy"][0]["start"] == "2026-10-19T15:00:00+05:00"
    assert result["busy"][21]["start"] == "2026-10-26T15:00:00+05:00"
    assert any(row["start_time"] == "13:05" for row in result["weekly_rules"])
    assert "—" in result["weekly_rules"][0]["source_quote"]
    assert not result["exams"]
    assert any("После этой даты" in warning for warning in result["warnings"])


def test_weekly_anchor_normalizes_to_monday_and_next_week_is_explicit():
    current = parse_schedule(WEEKLY_SCHEDULE, anchor_date="2026-10-20", weeks=20)
    following = parse_schedule(WEEKLY_SCHEDULE, anchor_date="2026-10-26", weeks=2)
    assert current["week_start"] == "2026-10-19" and len(current["busy"]) == 420
    assert following["week_start"] == "2026-10-26" and len(following["busy"]) == 42
    assert all(datetime.fromisoformat(row["start"]).weekday() < 5 for row in following["busy"])


@pytest.mark.parametrize("kwargs", [{"anchor_date": "not a date"}, {"weeks": 0}, {"weeks": 21}, {"weeks": 1.5}])
def test_invalid_weekly_repetition_is_rejected(kwargs):
    with pytest.raises(ValueError):
        parse_schedule(WEEKLY_SCHEDULE, **kwargs)


def test_russian_weekday_headings_and_exam_table_are_not_confused():
    weekly = parse_schedule("## Понедельник\n09:00–09:50 — Математика | лекция | А101", anchor_date="2026-10-19", weeks=1)
    assert weekly["weekly_count"] == 1 and weekly["busy"][0]["title"] == "Математика"
    exam = parse_schedule("Exam schedule\nMonday\n10:00-11:00 Mathematics | exam", anchor_date="2026-10-19")
    assert not exam["busy"] and exam["recurring"] is False
    dated = parse_schedule("25.05 10:00-11:00 Mathematics | examf", year=2026, anchor_date="2030-10-21", weeks=20)
    assert dated["recurring"] is False and dated["busy"][0]["start"].startswith("2026-05-25")


@pytest.mark.parametrize("separator", [" — ", ": ", " ", " | "])
@pytest.mark.parametrize("values", [(20, 10, 15, 15, 40), (8.5, 21.5, 7.25, 22.75, 40), (5, 20, 25, 10, 40)])
def test_point_scheme_generalizes_names_weights_order_and_plain_text(separator, values):
    a, b, c, d, final = values
    first, second = a + b, c + d
    lines = ["## Course title:Project Management", "Number of credits: 3",
             "1st Attestation", f"Weight: Maximum {first} points ({first}% of the final grade)",
             f"Research notebook{separator}{a} points", f"Oral defense{separator}{b} points",
             "2nd Attestation", f"Weight: Max {second} points ({second}% of final grade)",
             f"Case study{separator}{c} points", f"Portfolio{separator}{d} points",
             "Final Exam", f"Weight: Max {final} points ({final}% final grade)",
             f"Capstone assessment{separator}{final} points"]
    result = parse_syllabus("\n".join(lines))
    assert result["course"]["name"] == "Project Management" and result["course"]["credits"] == 3
    rows = result["course"]["components"]
    assert [row["name"] for row in rows] == ["Research notebook", "Oral defense", "Case study", "Portfolio", "Capstone assessment"]
    assert [row["weight"] for row in rows] == list(values)
    assert [row["max_score"] for row in rows] == list(values)
    assert result["confidence"] == .95


def test_explicit_point_maxima_use_raw_scores_while_original_hpc_weight_table_uses_percent_scores():
    from campuspulse.academic import analyze_course

    raw = parse_syllabus(POINT_SYLLABUS, name="Project Management")["course"]
    raw["credits"] = 5
    raw["components"][0]["score"] = 15
    analyzed = analyze_course(raw)
    assert raw["components"][0]["max_score"] == 18
    assert analyzed["earned_points"] == 15 and analyzed["current_average"] == pytest.approx(15 / 18 * 100, abs=1e-6)
    for row in raw["components"]:
        row["score"] = row["max_score"]
    assert analyze_course(raw)["earned_points"] == 100
    assert all(row["max_score"] == 100 for row in parse_syllabus(EXAMPLE_SYLLABUS_TEXT)["course"]["components"])
    assert any("Оценки вводятся в баллах" in warning for warning in parse_syllabus(POINT_SYLLABUS)["warnings"])


def test_arbitrary_explicit_percentage_names_are_preserved_and_policy_percentages_are_not_assessments():
    text = """Course title:Academic Writing
Number of credits:3
Final Grade:100%
Essay 1—35%
Oral Presentation—25%
Final Exam—40%
Policy:25%
Automatic Fail Rule: less than 25%
If your midterm score is below 25%
Total:100%"""
    result = parse_syllabus(text)
    assert result["course"]["name"] == "Academic Writing" and result["course"]["credits"] == 3
    assert [(row["name"], row["weight"]) for row in result["course"]["components"]] == [
        ("Essay 1", 35), ("Oral Presentation", 25), ("Final Exam", 40)]
    assert all(row["max_score"] == 100 for row in result["course"]["components"])


def test_near_100_totals_and_compensating_group_errors_are_not_silently_repaired():
    flat = parse_syllabus("Essay:20%\nViva:10%\nDiscussion:29.9999%\nPortfolio:40%", name="Different subject")
    assert flat["confidence"] <= .4 and any("Сумма" in warning for warning in flat["warnings"])
    contradictory = POINT_SYLLABUS.replace("**18 points**", "**18.0001 points**", 1).replace("**12 points**", "**11.9999 points**", 2)
    result = parse_syllabus(contradictory)
    assert result["confidence"] <= .4 and result["warnings"]
    assert sum(row["weight"] for row in result["course"]["components"]) != 100


def test_named_rows_can_change_order_and_conflicting_repeated_group_weights_are_flagged():
    first = "  - **MCQ Test 1** (Week 4, based on Lectures 1–3, 50 questions) — **18 points**"
    second = "  - **Team Project 1** (Report and oral defense, Week 5) — **12 points**"
    reordered = parse_syllabus(POINT_SYLLABUS.replace(first + "\n" + second, second + "\n" + first))
    assert [(row["name"], row["weight"]) for row in reordered["course"]["components"][:2]] == [
        ("Team Project 1", 12), ("MCQ Test 1", 18)]
    inconsistent = POINT_SYLLABUS.replace("- **Weight:** Max **30 points** (30% of the final grade)",
        "Weight: Max 40 points (40% of final grade)\nWeight: Max 30 points (30% of final grade)", 1)
    result = parse_syllabus(inconsistent)
    assert result["confidence"] <= .4 and any("противоречиво" in warning for warning in result["warnings"])
    assert not result["course"]["components"]


@pytest.mark.parametrize("weekday", ["Monday", "monday", "Понедельник"])
def test_inline_weekday_colon_and_unicode_dash_form_a_weekly_rule(weekday):
    text = f"{weekday}: 15:00–15:50 — Biology | lecture | B101\nFriday: 12:00-12:45 — History | practice | H2"
    result = parse_schedule(text, anchor_date="2026-10-19", weeks=1)
    assert result["weekly_count"] == 2 and result["recurring"] is True
    assert result["courses"] == ["Biology", "History"]
    assert result["busy"][0]["start"] == "2026-10-19T15:00:00+05:00"
    assert result["busy"][1]["start"] == "2026-10-23T12:00:00+05:00"
    assert result["weekly_rules"][0]["source_quote"] == text.splitlines()[0]
