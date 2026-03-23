.PHONY: setup install-hooks precommit prepush lint typecheck test-public test-metadata test

setup:
	python -m pip install -e ".[test]"

install-hooks:
	python -m pre_commit install --install-hooks --hook-type pre-commit --hook-type pre-push

precommit:
	python -m pre_commit run --all-files

prepush:
	python -m pre_commit run --all-files --hook-stage pre-push

lint:
	python -m ruff check .

typecheck:
	python -m mypy

test-public:
	python -m pytest tests/test_public_api.py tests/test_public_smoke.py -q

test-metadata:
	python -m pytest tests/test_package_metadata.py -q

test:
	python -m pytest -q