import json
import os
import sqlite3

import pytest

from kycortex_agents.exceptions import StatePersistenceError
from kycortex_agents.memory.state_store import BaseStateStore, JsonStateStore, SqliteStateStore, resolve_state_store


class DelegatingStateStore(BaseStateStore):
    def save(self, path, data):
        return super().save(path, data)

    def load(self, path):
        return super().load(path)


def test_base_state_store_methods_raise_not_implemented():
    store = DelegatingStateStore()

    with pytest.raises(NotImplementedError):
        store.save("state.json", {})

    with pytest.raises(NotImplementedError):
        store.load("state.json")


def test_resolve_state_store_uses_sqlite_for_supported_extensions():
    assert isinstance(resolve_state_store("state.sqlite"), SqliteStateStore)
    assert isinstance(resolve_state_store("STATE.DB"), SqliteStateStore)
    assert isinstance(resolve_state_store("state.json"), JsonStateStore)
    assert isinstance(resolve_state_store("state.unknown"), JsonStateStore)


def test_json_state_store_save_and_load_round_trip(tmp_path):
    state_path = tmp_path / "state" / "project_state.json"
    store = JsonStateStore()
    payload = {"project_name": "Demo", "tasks": [{"id": "arch"}]}

    store.save(str(state_path), payload)

    assert store.load(str(state_path)) == payload


def test_json_state_store_save_and_load_round_trip_without_parent_directory(tmp_path):
    state_path = tmp_path / "project_state.json"
    store = JsonStateStore()
    payload = {"project_name": "Demo", "tasks": [{"id": "arch"}]}

    store.save(str(state_path), payload)

    assert store.load(str(state_path)) == payload


def test_json_state_store_save_and_load_round_trip_with_relative_path_and_no_parent_dir(tmp_path, monkeypatch):
    store = JsonStateStore()
    payload = {"project_name": "Demo", "tasks": [{"id": "arch"}]}

    monkeypatch.chdir(tmp_path)

    store.save("project_state.json", payload)

    assert os.path.exists(tmp_path / "project_state.json")
    assert store.load("project_state.json") == payload


def test_json_state_store_cleans_up_temp_file_after_replace_failure(tmp_path, monkeypatch):
    state_path = tmp_path / "state" / "project_state.json"
    store = JsonStateStore()

    def failing_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr("kycortex_agents.memory.state_store.os.replace", failing_replace)

    with pytest.raises(StatePersistenceError, match="Failed to save project state"):
        store.save(str(state_path), {"project_name": "Demo"})

    leftovers = list((tmp_path / "state").glob("project_state_*.json"))
    assert leftovers == []


def test_json_state_store_ignores_temp_cleanup_failure_after_replace_failure(tmp_path, monkeypatch):
    state_path = tmp_path / "state" / "project_state.json"
    store = JsonStateStore()

    def failing_replace(source, target):
        raise OSError("replace failed")

    def failing_remove(path):
        raise OSError("remove failed")

    monkeypatch.setattr("kycortex_agents.memory.state_store.os.replace", failing_replace)
    monkeypatch.setattr("kycortex_agents.memory.state_store.os.remove", failing_remove)

    with pytest.raises(StatePersistenceError, match="Failed to save project state"):
        store.save(str(state_path), {"project_name": "Demo"})


def test_json_state_store_rejects_missing_and_invalid_files(tmp_path):
    store = JsonStateStore()
    missing_path = tmp_path / "missing.json"
    invalid_path = tmp_path / "broken.json"
    invalid_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(StatePersistenceError, match="file not found"):
        store.load(str(missing_path))

    with pytest.raises(StatePersistenceError, match="invalid JSON"):
        store.load(str(invalid_path))


def test_sqlite_state_store_save_and_load_round_trip(tmp_path):
    state_path = tmp_path / "state" / "project_state.sqlite"
    store = SqliteStateStore()
    payload = {"project_name": "Demo", "tasks": [{"id": "arch"}]}

    store.save(str(state_path), payload)

    assert store.load(str(state_path)) == payload


def test_sqlite_state_store_save_and_load_round_trip_without_parent_directory(tmp_path):
    state_path = tmp_path / "project_state.sqlite"
    store = SqliteStateStore()
    payload = {"project_name": "Demo", "tasks": [{"id": "arch"}]}

    store.save(str(state_path), payload)

    assert store.load(str(state_path)) == payload


def test_sqlite_state_store_save_and_load_round_trip_with_relative_path_and_no_parent_dir(tmp_path, monkeypatch):
    store = SqliteStateStore()
    payload = {"project_name": "Demo", "tasks": [{"id": "arch"}]}

    monkeypatch.chdir(tmp_path)

    store.save("project_state.sqlite", payload)

    assert os.path.exists(tmp_path / "project_state.sqlite")
    assert store.load("project_state.sqlite") == payload


def test_sqlite_state_store_overwrites_existing_payload(tmp_path):
    state_path = tmp_path / "project_state.sqlite"
    store = SqliteStateStore()

    store.save(str(state_path), {"project_name": "Demo", "phase": "init"})
    store.save(str(state_path), {"project_name": "Demo", "phase": "completed"})

    assert store.load(str(state_path))["phase"] == "completed"

    connection = sqlite3.connect(state_path)
    row_count = connection.execute("SELECT COUNT(*) FROM project_state").fetchone()[0]
    connection.close()
    assert row_count == 1


def test_sqlite_state_store_rejects_missing_invalid_schema_and_invalid_payload(tmp_path):
    store = SqliteStateStore()
    missing_path = tmp_path / "missing.sqlite"
    invalid_schema_path = tmp_path / "invalid_schema.sqlite"
    invalid_payload_path = tmp_path / "invalid_payload.sqlite"

    with pytest.raises(StatePersistenceError, match="file not found"):
        store.load(str(missing_path))

    connection = sqlite3.connect(invalid_schema_path)
    with connection:
        connection.execute("CREATE TABLE wrong_table (id INTEGER PRIMARY KEY)")
    connection.close()

    with pytest.raises(StatePersistenceError, match="invalid SQLite"):
        store.load(str(invalid_schema_path))

    connection = sqlite3.connect(invalid_payload_path)
    with connection:
        connection.execute(
            """
            CREATE TABLE project_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO project_state (id, payload, updated_at) VALUES (1, ?, '2026-03-22T10:00:00+00:00')",
            ("{not-json",),
        )
    connection.close()

    with pytest.raises(StatePersistenceError, match="invalid SQLite"):
        store.load(str(invalid_payload_path))


def test_sqlite_state_store_rejects_missing_project_state_row(tmp_path):
    store = SqliteStateStore()
    invalid_payload_path = tmp_path / "missing_row.sqlite"

    connection = sqlite3.connect(invalid_payload_path)
    with connection:
        connection.execute(
            """
            CREATE TABLE project_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
    connection.close()

    with pytest.raises(StatePersistenceError, match="invalid SQLite"):
        store.load(str(invalid_payload_path))


def test_sqlite_state_store_serializes_non_json_native_values(tmp_path):
    state_path = tmp_path / "project_state.sqlite"
    store = SqliteStateStore()
    payload = {"metadata": {"raw": object()}}

    store.save(str(state_path), payload)

    loaded = store.load(str(state_path))

    assert isinstance(loaded["metadata"]["raw"], str)


def test_sqlite_state_store_save_wraps_connection_errors(tmp_path, monkeypatch):
    state_path = tmp_path / "project_state.sqlite"
    store = SqliteStateStore()

    def failing_connect(path):
        raise sqlite3.Error("boom")

    monkeypatch.setattr("kycortex_agents.memory.state_store.sqlite3.connect", failing_connect)

    with pytest.raises(StatePersistenceError, match="Failed to save project state"):
        store.save(str(state_path), {"project_name": "Demo"})


def test_sqlite_state_store_load_wraps_connection_errors(tmp_path, monkeypatch):
    state_path = tmp_path / "project_state.sqlite"
    state_path.write_text("placeholder", encoding="utf-8")
    store = SqliteStateStore()

    def failing_connect(path):
        raise sqlite3.Error("boom")

    monkeypatch.setattr("kycortex_agents.memory.state_store.sqlite3.connect", failing_connect)

    with pytest.raises(StatePersistenceError, match="invalid SQLite"):
        store.load(str(state_path))


def test_sqlite_state_store_load_wraps_query_errors_and_closes_connection(tmp_path, monkeypatch):
    state_path = tmp_path / "project_state.sqlite"
    state_path.write_text("placeholder", encoding="utf-8")
    store = SqliteStateStore()

    class FailingConnection:
        def __init__(self):
            self.closed = False

        def execute(self, query):
            raise sqlite3.Error("boom")

        def close(self):
            self.closed = True

    connection = FailingConnection()
    monkeypatch.setattr("kycortex_agents.memory.state_store.sqlite3.connect", lambda path: connection)

    with pytest.raises(StatePersistenceError, match="invalid SQLite"):
        store.load(str(state_path))

    assert connection.closed is True


def test_json_state_store_serializes_non_json_native_values(tmp_path):
    state_path = tmp_path / "project_state.json"
    store = JsonStateStore()
    payload = {"metadata": {"raw": object()}}

    store.save(str(state_path), payload)

    loaded = json.loads(state_path.read_text(encoding="utf-8"))
    assert isinstance(loaded["metadata"]["raw"], str)