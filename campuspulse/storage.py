import json
import os
from pathlib import Path
import sqlite3


class SQLiteStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (sid TEXT, kind TEXT, id TEXT, body TEXT, PRIMARY KEY(sid,kind,id))")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def list(self, sid, kind):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM records WHERE sid=? AND kind=? ORDER BY id", (sid, kind)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get(self, sid, kind, key):
        with self.connect() as db:
            row = db.execute("SELECT body FROM records WHERE sid=? AND kind=? AND id=?", (sid, kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, sid, kind, key, body):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?)", (sid, kind, key, json.dumps(body, ensure_ascii=False)))

    def put_once(self, sid, kind, key, body):
        with self.connect() as db:
            return bool(db.execute("INSERT OR IGNORE INTO records VALUES (?,?,?,?)", (sid, kind, key, json.dumps(body, ensure_ascii=False))).rowcount)

    def delete(self, sid, kind, key):
        with self.connect() as db:
            return bool(db.execute("DELETE FROM records WHERE sid=? AND kind=? AND id=?", (sid, kind, key)).rowcount)

    def update(self, sid, kind, key, transform):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM records WHERE sid=? AND kind=? AND id=?", (sid, kind, key)).fetchone()
            if not row:
                return None
            body = transform(json.loads(row[0]))
            db.execute("UPDATE records SET body=? WHERE sid=? AND kind=? AND id=?", (json.dumps(body, ensure_ascii=False), sid, kind, key))
            return body

    def clear(self, sid):
        with self.connect() as db:
            db.execute("DELETE FROM records WHERE sid=?", (sid,))


class FirestoreStore:
    def __init__(self, project):
        from google.cloud import firestore
        self.client = firestore.Client(project=project)

    def collection(self, sid, kind):
        return self.client.collection("campuspulse_sessions").document(sid).collection(kind)

    def list(self, sid, kind):
        return [d.to_dict() for d in self.collection(sid, kind).stream()]

    def get(self, sid, kind, key):
        return self.collection(sid, kind).document(key).get().to_dict()

    def put(self, sid, kind, key, body):
        self.collection(sid, kind).document(key).set(body)

    def put_once(self, sid, kind, key, body):
        from google.api_core.exceptions import AlreadyExists
        try:
            self.collection(sid, kind).document(key).create(body)
            return True
        except AlreadyExists:
            return False

    def delete(self, sid, kind, key):
        doc = self.collection(sid, kind).document(key)
        existed = doc.get().exists
        doc.delete()
        return existed

    def update(self, sid, kind, key, transform):
        from google.cloud import firestore
        ref = self.collection(sid, kind).document(key)
        @firestore.transactional
        def change(transaction):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                return None
            body = transform(snapshot.to_dict())
            transaction.set(ref, body)
            return body
        return change(self.client.transaction())

    def clear(self, sid):
        for kind in ("tasks", "materials", "meta", "private", "quests", "quest_rewards", "calendar_events"):
            for doc in self.collection(sid, kind).stream():
                doc.reference.delete()


def make_store():
    backend = os.getenv("STORAGE_BACKEND", "sqlite")
    if backend == "firestore":
        return FirestoreStore(os.environ["GOOGLE_CLOUD_PROJECT"])
    if backend != "sqlite":
        raise ValueError("STORAGE_BACKEND должен быть sqlite или firestore")
    return SQLiteStore(Path(os.getenv("DATA_DIR", "data")) / "campuspulse.db")
