.PHONY: setup install-hooks precommit prepush lint typecheck coverage package-check release-metadata-check release-check test-public test-metadata test

PYTHON ?= python3

setup:
	$(PYTHON) -m pip install -e ".[test]"

install-hooks:
	$(PYTHON) -m pre_commit install --install-hooks --hook-type pre-commit --hook-type pre-push

precommit:
	$(PYTHON) -m pre_commit run --all-files

prepush:
	$(PYTHON) -m pre_commit run --all-files --hook-stage pre-push

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

coverage:
	$(PYTHON) -m pytest --cov=kycortex_agents --cov-report=term-missing --cov-report=xml -q

package-check:
	$(PYTHON) scripts/package_check.py

release-metadata-check:
	$(PYTHON) scripts/release_metadata_check.py

release-check:
	$(PYTHON) scripts/release_check.py

test-public:
	$(PYTHON) -m pytest tests/test_public_api.py tests/test_public_smoke.py -q

test-metadata:
	$(PYTHON) -m pytest tests/test_package_metadata.py -q

test:
	$(PYTHON) -m pytest -q