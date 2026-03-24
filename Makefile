.PHONY: setup install-hooks precommit prepush lint typecheck coverage package-check release-metadata-check release-check test-public test-metadata test

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

coverage:
	python -m pytest --cov=kycortex_agents --cov-report=term-missing --cov-report=xml -q

package-check:
	python scripts/package_check.py

release-metadata-check:
	python scripts/release_metadata_check.py

release-check:
	python scripts/release_check.py

test-public:
	python -m pytest tests/test_public_api.py tests/test_public_smoke.py -q

test-metadata:
	python -m pytest tests/test_package_metadata.py -q

test:
	python -m pytest -q