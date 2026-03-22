import pytest


@pytest.fixture(autouse=True)
def isolate_test_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)