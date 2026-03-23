# Contributing

## Development Setup

1. Clone the repository.
2. Create or activate a Python 3.10+ environment.
3. Install the editable development environment:

```bash
pip install -e ".[test]"
```

## Workflow

1. Make a focused change.
2. Add or update tests for the behavior you changed.
3. Run the relevant test subset locally.
4. Run the full test suite before opening a pull request.

```bash
python -m pytest -q
```

## Pull Requests

1. Keep changes small and scoped to one concern.
2. Update documentation when public behavior or usage changes.
3. Preserve backward compatibility unless the change explicitly updates the public contract.
4. Include a clear summary of the problem, the fix, and the validation you ran.

## Quality Expectations

- Keep all repository content in English.
- Prefer minimal, well-tested changes over broad refactors.
- Do not commit generated build artifacts or local environment files.