from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Dict

from kycortex_agents.exceptions import StatePersistenceError


class BaseStateStore(ABC):
    @abstractmethod
    def save(self, path: str, data: Dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def load(self, path: str) -> Dict[str, Any]:
        raise NotImplementedError


class JsonStateStore(BaseStateStore):
    def save(self, path: str, data: Dict[str, Any]) -> None:
        state_dir = os.path.dirname(path)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(prefix="project_state_", suffix=".json", dir=state_dir or None)
        try:
            with os.fdopen(fd, "w") as file_handle:
                json.dump(data, file_handle, indent=2, default=str)
            os.replace(temp_path, path)
        except OSError as exc:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise StatePersistenceError(f"Failed to save project state to {path}") from exc

    def load(self, path: str) -> Dict[str, Any]:
        try:
            with open(path) as file_handle:
                return json.load(file_handle)
        except FileNotFoundError as exc:
            raise StatePersistenceError(f"Project state file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise StatePersistenceError(f"Project state file is invalid JSON: {path}") from exc


class SqliteStateStore(BaseStateStore):
    def save(self, path: str, data: Dict[str, Any]) -> None:
        state_dir = os.path.dirname(path)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)

        payload = json.dumps(data, default=str)
        try:
            connection = sqlite3.connect(path)
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_state (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO project_state (id, payload, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at
                    """,
                    (payload, datetime.now(UTC).isoformat()),
                )
        except sqlite3.Error as exc:
            raise StatePersistenceError(f"Failed to save project state to {path}") from exc
        finally:
            if 'connection' in locals():
                connection.close()

    def load(self, path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            raise StatePersistenceError(f"Project state file not found: {path}")
        try:
            connection = sqlite3.connect(path)
            row = connection.execute("SELECT payload FROM project_state WHERE id = 1").fetchone()
        except sqlite3.Error as exc:
            raise StatePersistenceError(f"Project state file is invalid SQLite: {path}") from exc
        finally:
            if 'connection' in locals():
                connection.close()

        if row is None:
            raise StatePersistenceError(f"Project state file is invalid SQLite: {path}")
        try:
            return json.loads(row[0])
        except json.JSONDecodeError as exc:
            raise StatePersistenceError(f"Project state file is invalid SQLite: {path}") from exc


def resolve_state_store(path: str) -> BaseStateStore:
    lower_path = path.lower()
    if lower_path.endswith((".sqlite", ".db")):
        return SqliteStateStore()
    return JsonStateStore()