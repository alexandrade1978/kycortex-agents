import json

import pytest

from kycortex_agents.exceptions import StatePersistenceError
from kycortex_agents.memory.project_state import ProjectState, Task


def test_save_and_load_project_state(tmp_path):
    state_path = tmp_path / "state" / "project_state.json"
    project = ProjectState(
        project_name="Demo",
        goal="Build demo",
        state_file=str(state_path),
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description="Design the architecture",
            assigned_to="architect",
        )
    )

    project.save()

    loaded = ProjectState.load(str(state_path))

    assert loaded.project_name == "Demo"
    assert loaded.goal == "Build demo"
    assert len(loaded.tasks) == 1
    assert loaded.tasks[0].id == "arch"


def test_load_rejects_invalid_json(tmp_path):
    state_path = tmp_path / "broken.json"
    state_path.write_text("{not-valid-json", encoding="utf-8")

    with pytest.raises(StatePersistenceError, match="invalid JSON"):
        ProjectState.load(str(state_path))


def test_load_rejects_missing_file(tmp_path):
    state_path = tmp_path / "missing.json"

    with pytest.raises(StatePersistenceError, match="file not found"):
        ProjectState.load(str(state_path))


def test_save_writes_valid_json(tmp_path):
    state_path = tmp_path / "project_state.json"
    project = ProjectState(project_name="Demo", goal="Build demo", state_file=str(state_path))

    project.save()

    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["project_name"] == "Demo"