"""Public persistence backends for JSON and SQLite project-state storage."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from abc import ABC, abstractmethod
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List

from kycortex_agents.exceptions import StatePersistenceError

if os.name == "posix":
    import fcntl

__all__ = [
    "BaseStateStore",
    "JsonStateStore",
    "SqliteStateStore",
    "list_state_snapshots",
    "load_state_snapshot",
    "resolve_state_store",
    "state_file_lock",
]

_SNAPSHOT_DIRECTORY_SUFFIX = ".history"


def _public_state_path_label(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


@contextmanager
def state_file_lock(path: str, *, exclusive: bool = True) -> Iterator[None]:
    """Hold an advisory lock on `<path>.lock` for the duration of a save or load.

    Locking is advisory and POSIX-only (`fcntl.flock`); on other platforms this is
    a no-op. Persisted state follows a single-writer contract: concurrent writers
    are serialized, but cooperating processes must all go through this lock.
    """

    if os.name != "posix":
        yield
        return
    lock_path = f"{path}.lock"
    lock_dir = os.path.dirname(lock_path)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    try:
        lock_file = open(lock_path, "a")
    except OSError as exc:
        raise StatePersistenceError(
            f"Failed to open state lock file for {_public_state_path_label(path)}"
        ) from exc
    try:
        try:
            os.chmod(lock_path, 0o600)
        except OSError:
            pass
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def _harden_state_file_permissions(path: str) -> None:
    if os.name != "posix":
        return
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        raise StatePersistenceError(
            f"Failed to lock down project state permissions for {_public_state_path_label(path)}"
        ) from exc


def _harden_state_directory_permissions(path: str) -> None:
    if os.name != "posix":
        return
    try:
        os.chmod(path, 0o700)
    except OSError as exc:
        raise StatePersistenceError(
            f"Failed to lock down project state directory permissions for {_public_state_path_label(path)}"
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

    def save_snapshot(self, path: str, data: Dict[str, Any], *, keep_last: int, prune: bool = True) -> None:
        """Append a versioned snapshot of the payload, pruning history beyond `keep_last` entries.

        When `prune` is False (for example under a legal hold) the snapshot is still
        appended but no history entries are removed. The default implementation is a
        no-op so custom stores remain compatible; built-in backends override it.
        """

    def list_snapshots(self, path: str) -> List[Dict[str, Any]]:
        """Return snapshot metadata (`version`, `saved_at`) in ascending version order."""

        return []

    def load_snapshot(self, path: str, version: int) -> Dict[str, Any]:
        """Load and return the payload stored for a specific snapshot version."""

        raise StatePersistenceError(
            f"Snapshot history is not supported for {_public_state_path_label(path)}"
        )


class JsonStateStore(BaseStateStore):
    """JSON-file persistence backend that saves project state atomically on disk."""

    def save(self, path: str, data: Dict[str, Any]) -> None:
        state_dir = os.path.dirname(path)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)
            _harden_state_directory_permissions(state_dir)

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

    def _snapshot_directory(self, path: str) -> str:
        return f"{path}{_SNAPSHOT_DIRECTORY_SUFFIX}"

    def _snapshot_entries(self, path: str) -> List[Dict[str, Any]]:
        snapshot_dir = self._snapshot_directory(path)
        if not os.path.isdir(snapshot_dir):
            return []
        entries: List[Dict[str, Any]] = []
        for filename in os.listdir(snapshot_dir):
            if not (filename.startswith("snapshot_") and filename.endswith(".json")):
                continue
            parts = filename[len("snapshot_"):-len(".json")].split("_", 1)
            if not parts[0].isdigit():
                continue
            entries.append(
                {
                    "version": int(parts[0]),
                    "saved_at": parts[1].replace("-", ":") if len(parts) > 1 else "",
                    "filename": filename,
                }
            )
        entries.sort(key=lambda entry: entry["version"])
        return entries

    def save_snapshot(self, path: str, data: Dict[str, Any], *, keep_last: int, prune: bool = True) -> None:
        if keep_last <= 0:
            return
        snapshot_dir = self._snapshot_directory(path)
        os.makedirs(snapshot_dir, exist_ok=True)
        _harden_state_directory_permissions(snapshot_dir)
        entries = self._snapshot_entries(path)
        next_version = entries[-1]["version"] + 1 if entries else 1
        saved_at = datetime.now(timezone.utc).isoformat().replace(":", "-")
        snapshot_path = os.path.join(snapshot_dir, f"snapshot_{next_version:08d}_{saved_at}.json")
        try:
            with open(snapshot_path, "w") as file_handle:
                json.dump(data, file_handle, indent=2, default=str)
        except OSError as exc:
            raise StatePersistenceError(
                f"Failed to save project state snapshot for {_public_state_path_label(path)}"
            ) from exc
        _harden_state_file_permissions(snapshot_path)
        if not prune:
            return
        for stale_entry in self._snapshot_entries(path)[:-keep_last]:
            try:
                os.remove(os.path.join(snapshot_dir, stale_entry["filename"]))
            except OSError:
                pass

    def list_snapshots(self, path: str) -> List[Dict[str, Any]]:
        return [
            {"version": entry["version"], "saved_at": entry["saved_at"]}
            for entry in self._snapshot_entries(path)
        ]

    def load_snapshot(self, path: str, version: int) -> Dict[str, Any]:
        for entry in self._snapshot_entries(path):
            if entry["version"] == version:
                snapshot_path = os.path.join(self._snapshot_directory(path), entry["filename"])
                return self.load(snapshot_path)
        raise StatePersistenceError(
            f"Project state snapshot version {version} not found for {_public_state_path_label(path)}"
        )


class SqliteStateStore(BaseStateStore):
    """SQLite persistence backend that stores the latest project-state payload transactionally."""

    def save(self, path: str, data: Dict[str, Any]) -> None:
        state_dir = os.path.dirname(path)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)
            _harden_state_directory_permissions(state_dir)

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

    def save_snapshot(self, path: str, data: Dict[str, Any], *, keep_last: int, prune: bool = True) -> None:
        if keep_last <= 0:
            return
        payload = json.dumps(data, default=str)
        try:
            with closing(sqlite3.connect(path)) as connection:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS project_state_history (
                            version INTEGER PRIMARY KEY AUTOINCREMENT,
                            payload TEXT NOT NULL,
                            saved_at TEXT NOT NULL
                        )
                        """
                    )
                    connection.execute(
                        "INSERT INTO project_state_history (payload, saved_at) VALUES (?, ?)",
                        (payload, datetime.now(timezone.utc).isoformat()),
                    )
                    if prune:
                        connection.execute(
                            """
                            DELETE FROM project_state_history
                            WHERE version NOT IN (
                                SELECT version FROM project_state_history
                                ORDER BY version DESC LIMIT ?
                            )
                            """,
                            (keep_last,),
                        )
        except sqlite3.Error as exc:
            raise StatePersistenceError(
                f"Failed to save project state snapshot for {_public_state_path_label(path)}"
            ) from exc

    def list_snapshots(self, path: str) -> List[Dict[str, Any]]:
        if not os.path.exists(path):
            return []
        try:
            with closing(sqlite3.connect(path)) as connection:
                rows = connection.execute(
                    """
                    SELECT version, saved_at FROM project_state_history
                    ORDER BY version ASC
                    """
                ).fetchall()
        except sqlite3.Error:
            return []
        return [{"version": row[0], "saved_at": row[1]} for row in rows]

    def load_snapshot(self, path: str, version: int) -> Dict[str, Any]:
        try:
            with closing(sqlite3.connect(path)) as connection:
                row = connection.execute(
                    "SELECT payload FROM project_state_history WHERE version = ?",
                    (version,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StatePersistenceError(
                f"Project state file is invalid SQLite: {_public_state_path_label(path)}"
            ) from exc
        if row is None:
            raise StatePersistenceError(
                f"Project state snapshot version {version} not found for {_public_state_path_label(path)}"
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


def list_state_snapshots(path: str) -> List[Dict[str, Any]]:
    """Return snapshot metadata for a state file in ascending version order."""

    return resolve_state_store(path).list_snapshots(path)


def load_state_snapshot(path: str, version: int) -> Dict[str, Any]:
    """Load the payload persisted for a specific snapshot version of a state file."""

    return resolve_state_store(path).load_snapshot(path, version)