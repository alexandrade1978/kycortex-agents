.PHONY: setup test-public test-metadata test

setup:
	python -m pip install -e ".[test]"

test-public:
	python -m pytest tests/test_public_api.py tests/test_public_smoke.py -q

test-metadata:
	python -m pytest tests/test_package_metadata.py -q

test:
	python -m pytest -q