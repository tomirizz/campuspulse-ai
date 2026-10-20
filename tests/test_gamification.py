"""Cosmetic fact deduplication must preserve old quiz attempts and earned XP."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib

import pytest

from campuspulse.progress import progress
from campuspulse.quests import answer_quest, start_quest
from campuspulse.storage import SQLiteStore
from campuspulse.study import quest_candidates, quest_fact_identity


def material(text, mid="demo"):
    return {"id": mid, "name": mid + ".txt", "page_count": 1,
            "pages": [{"page": 1, "text": text}]}


@pytest.mark.parametrize("left,right", [
    (("Mean", "sum of values"), ("MEAN", "  sum   of values. ")),
    (("Ёмкость", "Объём памяти"), ("Емкость", "объем памяти!")),
    (("ＡＢＣ", "ｓｕｍ　ｏｆ　ｖａｌｕｅｓ"), ("abc", "sum of values")),
    (("Café", "a term"), ("Cafe\u0301", "a term…")),
    (("Term", "definition;"), ("term", "definition")),
])
def test_cosmetic_variants_share_fact_identity(left, right):
    assert quest_fact_identity(*left) == quest_fact_identity(*right)


@pytest.mark.parametrize("left,right", [
    ("value 1.2", "value 12"), ("value 1,2", "value 12"),
    ("value -2", "value 2"), ("value 1/2", "value 12"),
    ("language C++", "language C"), ("value 10", "value 100"),
])
def test_distinct_numbers_and_internal_punctuation_do_not_merge(left, right):
    assert quest_fact_identity("Term", left) != quest_fact_identity("Term", right)


def test_same_bank_deduplicates_cosmetic_copies_without_changing_quotes():
    text = "Mean: sum of values.\nMEAN: sum  of values!"
    bank = quest_candidates(material(text))["questions"]
    assert len(bank) == 1
    assert bank[0]["source"]["quote"] == text.splitlines()[0]
    assert bank[0]["answer"] == "Mean"


def test_cosmetic_reuploads_and_concurrent_answers_only_award_once(tmp_path):
    store = SQLiteStore(tmp_path / "xp.db")
    sources = [material("Mean: sum of values.", "a"), material("MEAN: sum  of values!", "b")]
    sessions = []
    for index in range(12):
        source = sources[index % 2]
        question = quest_candidates(source)["questions"][0]
        session = start_quest(store, "student", source, [question["id"]])
        sessions.append((session["id"], question["id"]))
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda pair: answer_quest(store, "student", *pair, "mean"), sessions))
    rewards = store.list("student", "quest_rewards")
    assert len(rewards) == 1
    assert progress([], quest_rewards=rewards)["xp"] == 10
    assert not store.list("other-student", "quest_rewards")


def legacy_question_and_reward(source):
    question = quest_candidates(source)["questions"][0]
    # Previous releases hashed casefold only, including the final full stop.
    legacy_id = hashlib.sha256(b"mean\nsum of values.").hexdigest()
    question = {**question, "id": legacy_id}
    stamp = datetime.now(timezone.utc).isoformat()
    reward = {"id": legacy_id, "title": "Квест: Mean", "xp": 10, "at": stamp,
              "why": {"inputs": {"question_id": legacy_id, "источник": question["source"]}}}
    return question, reward


def test_legacy_reward_is_kept_and_reupload_does_not_award_again(tmp_path):
    store = SQLiteStore(tmp_path / "xp.db")
    source = material("Mean: sum of values.")
    old_question, old_reward = legacy_question_and_reward(source)
    store.put("student", "quest_rewards", old_reward["id"], old_reward)
    new_question = quest_candidates(material("MEAN: sum  of values!"))["questions"][0]
    assert new_question["id"] != old_question["id"]
    new_source = material("MEAN: sum  of values!")
    session = start_quest(store, "student", new_source, [new_question["id"]])
    answer_quest(store, "student", session["id"], new_question["id"], "mean")
    assert store.list("student", "quest_rewards") == [old_reward]
    assert progress([], quest_rewards=store.list("student", "quest_rewards"))["xp"] == 10


def test_legacy_quiz_can_continue_with_original_question_id(tmp_path):
    store = SQLiteStore(tmp_path / "xp.db")
    source = material("Mean: sum of values.")
    old_question, _ = legacy_question_and_reward(source)
    store.put("student", "quests", "legacy", {"id": "legacy", "material": source["name"],
              "questions": [old_question], "answers": []})
    result = answer_quest(store, "student", "legacy", old_question["id"], "mean")
    assert result["finished"] and result["score_percent"] == 100
    assert result["feedback"]["question_id"] == old_question["id"]
    rewards = store.list("student", "quest_rewards")
    assert len(rewards) == 1
    assert rewards[0]["question_id"] == old_question["id"]
    assert rewards[0]["id"] == quest_candidates(source)["questions"][0]["id"]
    answer_quest(store, "student", "legacy", old_question["id"], "wrong")
    assert store.list("student", "quest_rewards") == rewards
    assert store.get("student", "quests", "legacy")["questions"][0]["id"] == old_question["id"]
