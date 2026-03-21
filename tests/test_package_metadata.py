from pathlib import Path
import tomllib


def test_pyproject_contains_expected_package_metadata():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    project = data["project"]
    assert project["name"] == "kycortex-agents"
    assert project["version"] == "0.1.0"
    assert "Typing :: Typed" in project["classifiers"]
    assert "openai>=1.0.0,<2.0.0" in project["dependencies"]


def test_pyproject_configures_pytest_testpaths():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    pytest_config = data["tool"]["pytest"]["ini_options"]
    assert pytest_config["testpaths"] == ["tests"]
    assert pytest_config["python_files"] == ["test_*.py"]