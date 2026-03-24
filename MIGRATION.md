# Migration Notes

These notes describe the migration path from the early KYCortex prototype to the stabilized public surface shipped in KYCortex 1.0.0.

## Who Should Read This

- Users who adopted the repository before the public API surface was stabilized.
- Contributors updating older examples or local integrations that imported internal modules directly.
- Anyone moving from the original sequential prototype to the current dependency-aware workflow runtime.

## Main Migration Themes

### 1. Use the public package surface

Prefer imports from the top-level package and the public `workflows` module:

```python
from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task
```

Avoid relying on deep internal imports unless you are working on the package itself. The supported integration seams are the documented public exports, not private runtime helpers.

### 2. Migrate from sequential tasks to dependency-aware workflows

Older prototype usage assumed a mostly sequential task flow with implicit context passing. The current runtime supports explicit task dependencies and deterministic scheduling:

```python
project.add_task(
    Task(
        id="review",
        title="Review",
        description="Review the implementation",
        assigned_to="code_reviewer",
        dependencies=["code"],
    )
)
```

Use `dependencies=[...]` plus `workflow_failure_policy` and `workflow_resume_policy` to model workflow behavior explicitly.

### 3. Expect structured runtime state

Project state now persists more than plain task text. Snapshots and persisted state include:

- normalized task outputs
- artifacts
- decisions
- failure records
- execution events
- workflow lifecycle metadata

If you previously read raw task strings directly from saved state files, update your integration to use `ProjectSnapshot`, `TaskResult`, and related public types.

### 4. Expect provider abstraction instead of OpenAI-only behavior

The early prototype was tightly coupled to OpenAI-style execution. The current runtime supports:

- OpenAI
- Anthropic
- Ollama

Provider selection now belongs in `KYCortexConfig`, and provider-specific credentials are resolved through the documented configuration layer.

### 5. Prefer runtime-aware agents and registries

Custom integrations should extend the public runtime interfaces:

- `BaseAgent`
- `AgentRegistry`
- `BaseLLMProvider`
- `BaseStateStore`

Legacy `run(task_description, context)` compatibility still exists, but new integrations should prefer typed `AgentInput`-based execution paths.

## Practical Upgrade Checklist

1. Replace deep internal imports with top-level `kycortex_agents` imports where available.
2. Update workflow definitions to use explicit dependencies instead of assuming strict task order.
3. Review configuration for provider selection, failure policy, and resume policy behavior.
4. Re-run persisted workflow examples if you depend on state reload or failure recovery.
5. Validate built artifacts with `python scripts/package_check.py` before publishing local downstream integrations.

## Compatibility Notes

- The repository still exports compatibility paths for legacy agent protocol dispatch where practical.
- Persisted legacy states continue to load with safe defaults when newer fields are missing.
- The 1.0 release treats the documented public API as the supported stability boundary.

## Recommended Validation After Migration

Run at least the following before considering a migration complete:

```bash
python -m pytest tests/test_public_api.py tests/test_public_smoke.py -q
python -m pytest tests/test_package_metadata.py -q
python scripts/package_check.py
python -m pytest -q
```