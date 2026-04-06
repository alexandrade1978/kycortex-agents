"""Public persistence backends for JSON and SQLite project-state storage."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from abc import ABC, abstractmethod
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Dict

from kycortex_agents.exceptions import StatePersistenceError

__all__ = ["BaseStateStore", "JsonStateStore", "SqliteStateStore", "resolve_state_store"]


def _public_state_path_label(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def _harden_state_file_permissions(path: str) -> None:
    if os.name != "posix":
        return
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        raise StatePersistenceError(
            f"Failed to lock down project state permissions for {_public_state_path_label(path)}"
        ) from exc


class BaseStateStore(ABC):
    """Abstract persistence backend for saving and loading project state payloads."""

    @abstractmethod
    def save(self, path: str, data: Dict[str, Any]) -> None:
        """Persist the serialized project-state payload to the target path."""

        raise NotImplementedError

    @abstractmethod
    def load(self, path: str) -> Dict[str, Any]:
        """Load and return the serialized project-state payload from the target path."""

        raise NotImplementedError


class JsonStateStore(BaseStateStore):
    """JSON-file persistence backend that saves project state atomically on disk."""

    def save(self, path: str, data: Dict[str, Any]) -> None:
        state_dir = os.path.dirname(path)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(prefix="project_state_", suffix=".json", dir=state_dir or None)
        try:
            with os.fdopen(fd, "w") as file_handle:
                json.dump(data, file_handle, indent=2, default=str)
            os.replace(temp_path, path)
            _harden_state_file_permissions(path)
        except StatePersistenceError:
            raise
        except OSError as exc:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise StatePersistenceError(
                f"Failed to save project state to {_public_state_path_label(path)}"
            ) from exc

    def load(self, path: str) -> Dict[str, Any]:
        try:
            with open(path) as file_handle:
                return json.load(file_handle)
        except FileNotFoundError as exc:
            raise StatePersistenceError(
                f"Project state file not found: {_public_state_path_label(path)}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise StatePersistenceError(
                f"Project state file is invalid JSON: {_public_state_path_label(path)}"
            ) from exc


class SqliteStateStore(BaseStateStore):
    """SQLite persistence backend that stores the latest project-state payload transactionally."""

    def save(self, path: str, data: Dict[str, Any]) -> None:
        state_dir = os.path.dirname(path)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)

        payload = json.dumps(data, default=str)
        try:
            with closing(sqlite3.connect(path)) as connection:
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
                        (payload, datetime.now(timezone.utc).isoformat()),
                    )
            _harden_state_file_permissions(path)
        except StatePersistenceError:
            raise
        except sqlite3.Error as exc:
            raise StatePersistenceError(
                f"Failed to save project state to {_public_state_path_label(path)}"
            ) from exc

    def load(self, path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            raise StatePersistenceError(
                f"Project state file not found: {_public_state_path_label(path)}"
            )
        try:
            with closing(sqlite3.connect(path)) as connection:
                row = connection.execute("SELECT payload FROM project_state WHERE id = 1").fetchone()
        except sqlite3.Error as exc:
            raise StatePersistenceError(
                f"Project state file is invalid SQLite: {_public_state_path_label(path)}"
            ) from exc

        if row is None:
            raise StatePersistenceError(
                f"Project state file is invalid SQLite: {_public_state_path_label(path)}"
            )
        try:
            return json.loads(row[0])
        except json.JSONDecodeError as exc:
            raise StatePersistenceError(
                f"Project state file is invalid SQLite: {_public_state_path_label(path)}"
            ) from exc


def resolve_state_store(path: str) -> BaseStateStore:
    """Return the built-in persistence backend that matches the target state-file extension."""

    lower_path = path.lower()
    if lower_path.endswith((".sqlite", ".db")):
        return SqliteStateStore()
    return JsonStateStore()