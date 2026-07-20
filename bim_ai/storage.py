from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


AUDIT_LOG_FILENAME = "audit_events.jsonl"


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    ifc_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS viewer_selections (
    project_id INTEGER PRIMARY KEY,
    step_id INTEGER NOT NULL,
    ifc_type TEXT,
    global_id TEXT,
    name TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
    _migrate_audit_events(db_path)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def create_project(db_path: Path, name: str, ifc_path: str, original_filename: str) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, ifc_path, original_filename) VALUES (?, ?, ?)",
            (name, ifc_path, original_filename),
        )
        return int(cur.lastrowid)


def ensure_project(db_path: Path, name: str, ifc_path: str, original_filename: str) -> int:
    with connect(db_path) as conn:
        row = conn.execute("SELECT id FROM projects WHERE ifc_path = ?", (ifc_path,)).fetchone()
        if row is not None:
            return int(row["id"])
        cur = conn.execute(
            "INSERT INTO projects (name, ifc_path, original_filename) VALUES (?, ?, ?)",
            (name, ifc_path, original_filename),
        )
        return int(cur.lastrowid)


def list_projects(db_path: Path) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY name ASC, id ASC").fetchall()
    return rows_to_dicts(rows)


def get_project(db_path: Path, project_id: int) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ValueError(f"Project not found: {project_id}")
    return dict(row)


def create_conversation(
    db_path: Path,
    project_id: int,
    title: str,
    system_prompt: str,
) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO conversations (project_id, title, system_prompt)
            VALUES (?, ?, ?)
            """,
            (project_id, title, system_prompt),
        )
        return int(cur.lastrowid)


def list_conversations(db_path: Path, project_id: int) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC, id DESC",
            (project_id,),
        ).fetchall()
    return rows_to_dicts(rows)


def get_conversation(
    db_path: Path,
    conversation_id: int,
    project_id: int | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        if project_id is None:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND project_id = ?",
                (conversation_id, project_id),
            ).fetchone()
    if row is None:
        raise ValueError(f"Conversation not found: {conversation_id}")
    return dict(row)


def add_message(
    db_path: Path,
    conversation_id: int,
    role: str,
    content: str,
    project_id: int | None = None,
) -> int:
    with connect(db_path) as conn:
        if project_id is not None:
            conversation = conn.execute(
                "SELECT id FROM conversations WHERE id = ? AND project_id = ?",
                (conversation_id, project_id),
            ).fetchone()
            if conversation is None:
                raise ValueError(f"Conversation not found in project: {conversation_id}")
        cur = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content)
            VALUES (?, ?, ?)
            """,
            (conversation_id, role, content),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (conversation_id,),
        )
        return int(cur.lastrowid)


def list_messages(
    db_path: Path,
    conversation_id: int,
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        if project_id is None:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT m.* FROM messages AS m
                JOIN conversations AS c ON c.id = m.conversation_id
                WHERE m.conversation_id = ? AND c.project_id = ?
                ORDER BY m.id ASC
                """,
                (conversation_id, project_id),
            ).fetchall()
    return rows_to_dicts(rows)


def set_viewer_selection(
    db_path: Path,
    project_id: int,
    step_id: int,
    ifc_type: str | None = None,
    global_id: str | None = None,
    name: str | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO viewer_selections (project_id, step_id, ifc_type, global_id, name, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(project_id) DO UPDATE SET
                step_id = excluded.step_id,
                ifc_type = excluded.ifc_type,
                global_id = excluded.global_id,
                name = excluded.name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (project_id, step_id, ifc_type, global_id, name),
        )


def get_viewer_selection(db_path: Path, project_id: int) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM viewer_selections WHERE project_id = ?", (project_id,)).fetchone()
    return dict(row) if row is not None else None


def add_audit_event(
    db_path: Path,
    project_id: int,
    conversation_id: int | None,
    event_type: str,
    status: str,
    payload: dict[str, Any],
) -> int:
    event = {
        "id": uuid4().hex,
        "project_id": project_id,
        "conversation_id": conversation_id,
        "event_type": event_type,
        "status": status,
        "payload": payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _append_audit_event(db_path, event)
    return 0


def list_audit_events(
    db_path: Path,
    project_id: int,
    conversation_id: int | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    events = _read_audit_events(db_path)
    filtered = [
        event
        for event in events
        if event.get("project_id") == project_id
        and (conversation_id is None or event.get("conversation_id") == conversation_id)
    ]
    return list(reversed(filtered[-limit:]))


def _audit_log_path(db_path: Path) -> Path:
    return db_path.parent / AUDIT_LOG_FILENAME


def _append_audit_event(db_path: Path, event: dict[str, Any]) -> None:
    log_path = _audit_log_path(db_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def _read_audit_events(db_path: Path) -> list[dict[str, Any]]:
    log_path = _audit_log_path(db_path)
    if not log_path.is_file():
        return []

    events: list[dict[str, Any]] = []
    with log_path.open(encoding="utf-8") as log_file:
        for line in log_file:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _migrate_audit_events(db_path: Path) -> None:
    """Move audit rows created by earlier versions into the sibling JSONL log."""
    conn = connect(db_path)
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_events'"
        ).fetchone()
        if table is None:
            return
        rows = conn.execute("SELECT * FROM audit_events ORDER BY id ASC").fetchall()

        for row in rows:
            legacy_event = dict(row)
            legacy_event["payload"] = json.loads(legacy_event.pop("payload_json"))
            _append_audit_event(db_path, legacy_event)
        conn.execute("DROP TABLE audit_events")
    finally:
        conn.close()
