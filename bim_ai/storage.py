from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


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
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


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


def get_conversation(db_path: Path, conversation_id: int) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if row is None:
        raise ValueError(f"Conversation not found: {conversation_id}")
    return dict(row)


def add_message(
    db_path: Path,
    conversation_id: int,
    role: str,
    content: str,
) -> int:
    with connect(db_path) as conn:
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


def list_messages(db_path: Path, conversation_id: int) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    return rows_to_dicts(rows)
