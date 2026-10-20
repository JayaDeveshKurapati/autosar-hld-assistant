"""SQLite persistence: documents (with chunks + extraction), reviews, audit log."""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from .extract import Extraction, Port
from .ingest import Chunk

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project TEXT NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft', pages INTEGER NOT NULL, ingested_at REAL NOT NULL,
  chunks TEXT NOT NULL, extraction TEXT NOT NULL,
  UNIQUE(project, name, version)
);
CREATE TABLE IF NOT EXISTS reviews (
  doc_id INTEGER NOT NULL, finding_id TEXT NOT NULL, decision TEXT NOT NULL,
  note TEXT, reviewer TEXT, ts REAL NOT NULL, PRIMARY KEY (doc_id, finding_id)
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT, action TEXT NOT NULL, detail TEXT
);
"""


def extraction_from_dict(d: dict) -> Extraction:
    d = dict(d)
    d["ports"] = [Port(**p) for p in d.get("ports", [])]
    return Extraction(**d)


class Store:
    def __init__(self, path: str | Path = "data/hld.sqlite"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def audit(self, actor: str, action: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO audit(ts, actor, action, detail) VALUES (?,?,?,?)",
                        (time.time(), actor, action, detail))
        self.db.commit()

    def add_document(self, project: str, name: str, version: str, status: str, pages: int,
                     chunks: list[Chunk], ex: Extraction) -> int:
        cur = self.db.execute(
            "INSERT OR REPLACE INTO documents(project,name,version,status,pages,ingested_at,chunks,extraction)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (project, name, version, status, pages, time.time(),
             json.dumps([asdict(c) for c in chunks]), json.dumps(asdict(ex))))
        self.db.commit()
        return cur.lastrowid

    def list_documents(self, project: str | None = None) -> list[dict]:
        q = "SELECT id,project,name,version,status,pages,ingested_at FROM documents"
        rows = self.db.execute(q + (" WHERE project=?" if project else "") + " ORDER BY id", (project,) if project else ())
        return [dict(r) for r in rows]

    def get_document(self, doc_id: int) -> dict | None:
        r = self.db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["chunks"] = [Chunk(**c) for c in json.loads(d["chunks"])]
        d["extraction"] = extraction_from_dict(json.loads(d["extraction"]))
        return d

    def set_status(self, doc_id: int, status: str) -> None:
        self.db.execute("UPDATE documents SET status=? WHERE id=?", (status, doc_id))
        self.db.commit()

    def delete_document(self, doc_id: int) -> None:
        self.db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        self.db.execute("DELETE FROM reviews WHERE doc_id=?", (doc_id,))
        self.db.commit()

    def save_review(self, doc_id: int, finding_id: str, decision: str, note: str, reviewer: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?)",
                        (doc_id, finding_id, decision, note, reviewer, time.time()))
        self.db.commit()

    def reviews(self, doc_id: int) -> dict[str, dict]:
        rows = self.db.execute("SELECT * FROM reviews WHERE doc_id=?", (doc_id,))
        return {r["finding_id"]: dict(r) for r in rows}

    def audit_log(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]
