from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from campuspulse.academic_drafts import add_course_drafts, draft_courses, register_academic_drafts
from campuspulse.storage import FirestoreStore, SQLiteStore


@pytest.fixture
def store(tmp_path):
    return SQLiteStore(tmp_path / "drafts.db")


@pytest.fixture
def client(store):
    app = FastAPI()

    @app.middleware("http")
    async def session(request: Request, call_next):
        request.state.sid = request.headers.get("x-test-session", "student")
        return await call_next(request)

    register_academic_drafts(app, lambda: store)
    with TestClient(app) as value:
        yield value


def test_routes_create_names_only_without_invented_weights_or_credits(client):
    response = client.post("/api/academic/course-drafts", json={"names": ["  Math  ", "Writing"]})
    assert response.status_code == 200
    assert response.json()["created_count"] == 2
    drafts = response.json()["drafts"]
    assert {d["name"] for d in drafts} == {"Math", "Writing"}
    assert all(d["draft"] and d["needs_syllabus"] for d in drafts)
    assert all(set(d) == {"id", "name", "draft", "needs_syllabus", "created_at"} for d in drafts)
    assert client.get("/api/academic/course-drafts").json()["drafts"] == drafts


def test_repeated_names_casefold_and_existing_real_courses_are_skipped(store):
    store.put("student", "courses", "real", {"id": "real", "name": "Existing"})
    first = add_course_drafts(store, "student", ["Math", " MATH ", "Existing", "existing"])
    second = add_course_drafts(store, "student", [" math "])
    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert first["drafts"] == second["drafts"]
    assert len(store.list("student", "course_drafts")) == 1
    assert {name.casefold() for name in first["skipped_existing"]} == {"existing"}


def test_stable_id_after_delete_and_reimport_without_harming_real_course(client, store):
    first = client.post("/api/academic/course-drafts", json={"names": ["Math"]}).json()["drafts"][0]
    assert client.delete("/api/academic/course-drafts/" + first["id"]).status_code == 204
    second = client.post("/api/academic/course-drafts", json={"names": [" MATH "]}).json()["drafts"][0]
    assert second["id"] == first["id"]
    store.put("student", "courses", "real", {"id": "real", "name": "math"})
    assert draft_courses(store, "student") == []
    assert client.delete("/api/academic/course-drafts/" + second["id"]).status_code == 204
    assert store.get("student", "courses", "real") is not None


def test_session_isolation_and_delete_404(client, store):
    created = client.post("/api/academic/course-drafts", json={"names": ["Math"]}).json()["drafts"][0]
    assert client.get("/api/academic/course-drafts", headers={"x-test-session": "other"}).json()["drafts"] == []
    assert client.delete("/api/academic/course-drafts/" + created["id"], headers={"x-test-session": "other"}).status_code == 404
    assert len(draft_courses(store, "student")) == 1


@pytest.mark.parametrize("names", [[], [""], ["   "], ["a" * 161], ["Math"] * 41, [None], [42]])
def test_invalid_names_have_no_partial_writes(client, store, names):
    assert client.post("/api/academic/course-drafts", json={"names": names}).status_code == 422
    assert store.list("student", "course_drafts") == []


def test_shared_capacity_limit_is_checked_before_any_write(store):
    for index in range(38):
        store.put("student", "courses", str(index), {"id": str(index), "name": "Real " + str(index)})
    add_course_drafts(store, "student", ["First"])
    before = store.list("student", "course_drafts")
    with pytest.raises(ValueError, match="40"):
        add_course_drafts(store, "student", ["Second", "Third"])
    assert store.list("student", "course_drafts") == before
    assert add_course_drafts(store, "student", ["FIRST"])["created_count"] == 0


def test_parallel_reimports_are_idempotent(store):
    with ThreadPoolExecutor(max_workers=5) as pool:
        values = list(pool.map(lambda _: add_course_drafts(store, "student", ["Math", "Writing"]), range(5)))
    assert sum(value["created_count"] for value in values) == 2
    assert len(draft_courses(store, "student")) == 2


def test_sqlite_clear_removes_only_target_sessions_drafts(store):
    add_course_drafts(store, "student", ["Math"])
    add_course_drafts(store, "other", ["Writing"])
    store.clear("student")
    assert draft_courses(store, "student") == []
    assert len(draft_courses(store, "other")) == 1


def test_firestore_clear_includes_draft_collection_without_cloud_calls():
    deleted = []

    class Document:
        @property
        def reference(self):
            return self

        def delete(self):
            deleted.append("course_drafts")

    class Collection:
        def __init__(self, kind):
            self.kind = kind

        def stream(self):
            return [Document()] if self.kind == "course_drafts" else []

    fake = object.__new__(FirestoreStore)
    fake.collection = lambda sid, kind: Collection(kind)
    fake.clear("student")
    assert deleted == ["course_drafts"]
