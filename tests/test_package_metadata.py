from pathlib import Path
import re
import tomllib


def test_pyproject_contains_expected_package_metadata():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    project = data["project"]
    assert project["name"] == "kycortex-agents"
    assert project["version"] == "0.1.0"
    assert "Typing :: Typed" in project["classifiers"]
    assert "anthropic>=0.34.0,<1.0.0" in project["dependencies"]
    assert "openai>=1.0.0,<2.0.0" in project["dependencies"]


def test_pyproject_declares_test_extra():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    optional_dependencies = data["project"]["optional-dependencies"]
    assert optional_dependencies["test"] == ["pytest>=7.0.0"]


def test_pyproject_declares_explicit_setuptools_package_discovery():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    setuptools_config = data["tool"]["setuptools"]
    assert setuptools_config["include-package-data"] is True
    assert setuptools_config["packages"]["find"]["include"] == [
        "kycortex_agents",
        "kycortex_agents.*",
    ]


def test_typed_package_marker_exists_and_is_declared_in_package_data():
    project_root = Path(__file__).resolve().parents[1]
    pyproject_path = project_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert (project_root / "kycortex_agents" / "py.typed").is_file()
    assert data["tool"]["setuptools"]["package-data"]["kycortex_agents"] == ["py.typed"]


def test_pyproject_metadata_file_pointers_exist():
    project_root = Path(__file__).resolve().parents[1]
    pyproject_path = project_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    project = data["project"]
    assert (project_root / project["readme"]).is_file()
    assert (project_root / "LICENSE").is_file()


def test_top_level_contributing_guide_exists_for_readme_reference():
    project_root = Path(__file__).resolve().parents[1]

    assert (project_root / "CONTRIBUTING.md").is_file()


def test_readme_relative_markdown_links_resolve_to_existing_files():
    project_root = Path(__file__).resolve().parents[1]
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    relative_targets = re.findall(r"\[[^\]]+\]\(((?!https?://)[^)#]+)\)", readme)

    assert relative_targets
    for target in relative_targets:
        assert (project_root / target).is_file(), f"README link target does not exist: {target}"


def test_requirements_file_uses_package_test_extra_as_single_source_of_truth():
    requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    requirements_lines = [
        line.strip()
        for line in requirements_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert requirements_lines == ["-e .[test]"]


def test_readme_installation_flow_uses_package_installs():
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    assert "pip install ." in readme
    assert 'pip install -e ".[test]"' in readme
    assert "pip install -r requirements.txt" not in readme


def test_pyproject_configures_pytest_testpaths():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    pytest_config = data["tool"]["pytest"]["ini_options"]
    assert pytest_config["testpaths"] == ["tests"]
    assert pytest_config["python_files"] == ["test_*.py"]