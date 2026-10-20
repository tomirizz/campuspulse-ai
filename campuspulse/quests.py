"""Source-derived practice with user-approved answers and one-time rewards."""
from datetime import datetime, timezone
import uuid

from campuspulse.progress import proof
from campuspulse.study import quest_candidates, normalize_answer, quest_fact_from_source


def public_quest(quest):
    answers = quest.get("answers", [])
    index = len(answers)
    correct = sum(a["correct"] for a in answers)
    total = len(quest["questions"])
    current = quest["questions"][index] if index < total else None
    return {"id": quest["id"], "material": quest["material"], "total": total, "answered": index, "correct": correct,
            "score_percent": correct * 100 // total, "finished": index == total,
            "question": {k: current[k] for k in ("id", "question")} if current else None,
            "feedback": answers[-1] if answers else None,
            "why": proof("Как оценивается квест", "результат = floor(правильных / всех вопросов × 100%); награда = 10 XP за первый правильный ответ на уникальный факт",
            {"правильных": correct, "всего": total, "отвечено": index}, correct * 100 // total,
            "quests.public_quest + подтверждённые вами эталоны", "Сравнение без регистра, лишних пробелов, различия е/ё и конечной точки. Это тренировка воспроизведения текста.")}


def start_quest(store, sid, material, ids):
    if len(store.list(sid, "quests")) >= 100:
        raise ValueError("Доступно до 100 тренировок в одном пространстве")
    available = {q["id"]: q for q in quest_candidates(material)["questions"]}
    if len(set(ids)) != len(ids) or any(i not in available for i in ids):
        raise ValueError("Выберите существующие вопросы без повторений")
    value = {"id": uuid.uuid4().hex, "material": material["name"], "questions": [available[i] for i in ids], "answers": [],
             "approved_at": datetime.now(timezone.utc).isoformat()}
    store.put(sid, "quests", value["id"], value)
    return public_quest(value)


def answer_quest(store, sid, quest_id, question_id, answer):
    def update(quest):
        # A retried HTTP request returns the original result, not another attempt.
        if any(a["question_id"] == question_id for a in quest["answers"]):
            return quest
        index = len(quest["answers"])
        if index >= len(quest["questions"]) or quest["questions"][index]["id"] != question_id:
            raise ValueError("Ответьте на текущий вопрос квеста")
        question = quest["questions"][index]
        correct = normalize_answer(answer) == normalize_answer(question["answer"])
        feedback = {"question_id": question_id, "correct": correct, "submitted": answer, "expected": question["answer"],
                    "source": question["source"], "at": datetime.now(timezone.utc).isoformat(),
                    "why": proof("Почему ответ принят или отклонён", "normalize(ответ) == normalize(эталон)",
                    {"ответ": answer, "эталон": question["answer"]}, correct, question["source"]["file"], "Эталон взят из цитаты и подтверждён пользователем перед тренировкой.")}
        quest["answers"].append(feedback)
        return quest
    value = store.update(sid, "quests", quest_id, update)
    if not value:
        raise ValueError("Квест не найден в этом пространстве")
    # Keep all previously earned rows intact. Old releases keyed rewards by the
    # unnormalised question text; recover their canonical claim from the quote.
    claimed = set()
    for existing in store.list(sid, "quest_rewards"):
        claimed.add(existing["id"])
        if existing.get("fact_id"):
            claimed.add(existing["fact_id"])
        legacy_source = existing.get("why", {}).get("inputs", {}).get("источник")
        canonical = quest_fact_from_source(legacy_source)
        if canonical:
            claimed.add(canonical)
    # Idempotent inserts also repair a crash between saving an answer and awarding XP.
    for item in value["answers"]:
        if item["correct"]:
            identity = quest_fact_from_source(item["source"], item["expected"]) or item["question_id"]
            if identity in claimed:
                continue
            store.put_once(sid, "quest_rewards", identity, {
                "id": identity, "fact_id": identity, "question_id": item["question_id"],
                "title": "Квест: " + item["expected"], "xp": 10, "at": item["at"],
                "why": proof("Опыт за учебный квест", "10 XP × 1 уникальный правильно восстановленный факт", {"question_id": item["question_id"], "источник": item["source"]},
                10, "quests.answer_quest → quest_rewards", "Одинаковый факт даёт награду один раз, включая повторную загрузку того же материала.")})
            claimed.add(identity)
    return public_quest(value)
