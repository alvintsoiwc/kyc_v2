"""Persistent memory and checkpoints (SQLite).

Lec 4 "Memory categories / scope and storage":
  client facts – previously verified facts for a returning client (semantic memory).
                 Written ONLY after a compliance officer confirms them (controlled write),
                 never by the agent on its own.
  name variants– officer-confirmed entity name variants (e.g. Chinese / English employer names)
  cases        – summaries of completed runs (episodic memory)
  checkpoints  – one RunState snapshot per run, written after every node (resume)

Write lifecycle: finding -> officer review -> confirmed record with source run, date and confirmer.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS client_facts (
  fact_id TEXT PRIMARY KEY, client TEXT NOT NULL, category TEXT, statement TEXT, entity TEXT,
  amount REAL, currency TEXT, date TEXT, source_run TEXT, evidence TEXT, verified_on TEXT, confirmed_by TEXT);
CREATE TABLE IF NOT EXISTS name_variants (
  client TEXT NOT NULL, entity TEXT NOT NULL, variant TEXT NOT NULL, confirmed_by TEXT, updated_at TEXT,
  PRIMARY KEY (client, entity, variant));
CREATE TABLE IF NOT EXISTS cases (
  run_id TEXT PRIMARY KEY, client TEXT, created_at TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS checkpoints (
  run_id TEXT PRIMARY KEY, phase TEXT, updated_at TEXT, state TEXT);
"""


def norm_client(name: str) -> str:
    return " ".join(sorted(name.lower().replace(",", " ").replace(".", " ").split()))


class Memory:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _exec(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            cur = self.conn.execute(sql, args)
            rows = cur.fetchall()
            self.conn.commit()
            return rows

    # ------------------------------------------------------------ client facts (semantic)
    def client_facts(self, client: str) -> list[dict[str, Any]]:
        rows = self._exec("SELECT fact_id, category, statement, entity, amount, currency, date, source_run, evidence, "
                          "verified_on, confirmed_by FROM client_facts WHERE client=? ORDER BY date",
                          (norm_client(client),))
        keys = ["fact_id", "category", "statement", "entity", "amount", "currency", "date", "source_run", "evidence",
                "verified_on", "confirmed_by"]
        return [dict(zip(keys, r)) for r in rows]

    def add_client_fact(self, client: str, fact: dict[str, Any], *, source_run: str, confirmed_by: str,
                        verified_on: str | None = None) -> str:
        if not confirmed_by:
            raise ValueError("client facts are written only with an officer's confirmation")
        fid = fact.get("fact_id") or uuid.uuid4().hex[:8]
        self._exec("INSERT OR REPLACE INTO client_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (fid, norm_client(client), fact.get("category", ""), fact.get("statement", ""),
                    fact.get("entity", ""), fact.get("amount"), fact.get("currency", ""), fact.get("date", ""),
                    source_run, json.dumps(fact.get("evidence", [])), verified_on or time.strftime("%Y-%m-%d"),
                    confirmed_by))
        return fid

    # ------------------------------------------------------------ name variants
    def name_variants(self, client: str) -> list[dict[str, str]]:
        rows = self._exec("SELECT entity, variant FROM name_variants WHERE client=?", (norm_client(client),))
        return [{"entity": r[0], "variant": r[1]} for r in rows]

    def add_name_variant(self, client: str, entity: str, variant: str, confirmed_by: str) -> None:
        if not variant.strip() or variant.strip().lower() == entity.strip().lower():
            return
        self._exec("INSERT OR REPLACE INTO name_variants VALUES (?,?,?,?,?)",
                   (norm_client(client), entity.strip(), variant.strip(), confirmed_by, time.strftime("%Y-%m-%d")))

    # ------------------------------------------------------------ episodic
    def record_case(self, run_id: str, client: str, summary: dict[str, Any]) -> None:
        self._exec("INSERT OR REPLACE INTO cases VALUES (?,?,?,?)",
                   (run_id, norm_client(client), time.strftime("%Y-%m-%d"), json.dumps(summary)))

    def past_cases(self, client: str, limit: int = 3) -> list[dict[str, Any]]:
        rows = self._exec("SELECT run_id, created_at, summary FROM cases WHERE client=? "
                          "ORDER BY created_at DESC LIMIT ?", (norm_client(client), limit))
        return [{"run_id": r[0], "date": r[1], **json.loads(r[2])} for r in rows]

    # ------------------------------------------------------------ checkpoints
    def save_checkpoint(self, run_id: str, phase: str, state_json: str) -> None:
        self._exec("INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?)",
                   (run_id, phase, time.strftime("%Y-%m-%dT%H:%M:%S"), state_json))

    def load_checkpoint(self, run_id: str) -> tuple[str, str] | None:
        rows = self._exec("SELECT phase, state FROM checkpoints WHERE run_id=?", (run_id,))
        return (rows[0][0], rows[0][1]) if rows else None

    def latest_run_id(self) -> str | None:
        rows = self._exec("SELECT run_id FROM checkpoints ORDER BY updated_at DESC LIMIT 1")
        return rows[0][0] if rows else None


def seed_case_memory(db_path: Path, case_dir: Path | None, client: str) -> int:
    """Load a demo case's earlier officer-verified facts (returning-client scenario) into client memory."""
    if not case_dir or not (case_dir / "case.json").exists():
        return 0
    facts = json.loads((case_dir / "case.json").read_text(encoding="utf-8")).get("memory", [])
    if facts:
        mem = Memory(db_path)
        for f in facts:
            mem.add_client_fact(client, f, source_run="case-seed", confirmed_by=f["confirmed_by"],
                                verified_on=f.get("verified_on"))
        mem.close()
    return len(facts)
