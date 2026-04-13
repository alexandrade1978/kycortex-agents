# Incident Log - c74e957

Status: incident and rollback decision recorded

The canary window opened on `2026-04-13T02:34:33Z` and was aborted on `2026-04-13T02:49:28.144777+00:00`.

## Entries

- 2026-04-13T02:34:45.948542+00:00: No provider-health incident before traffic. OpenAI, Anthropic, and Ollama all reported `status=healthy` in the live preflight checkpoint.
- 2026-04-13T02:35:04.405705+00:00: No canary incident at the first controlled checkpoint. `release_user_smoke_openai` finished `completed`, remained externally valid, and did not trigger any rollback rule.
- 2026-04-13T02:47:53.463682+00:00: No provider-health incident before broader admission. OpenAI, Anthropic, and Ollama all remained `status=healthy` in the expansion checkpoint.
- 2026-04-13T02:49:28.144777+00:00: `SEV1` code-validation incident on controlled workflow `release_user_smoke_ollama`. The workflow completed all 3 tasks internally, but `examples/example_release_user_smoke.py` rewrote the persisted result to `phase=failed`, `terminal_outcome=failed`, `failure_category=code_validation`, and `acceptance_criteria_met=false` because importing `artifacts/code_implementation.py` found no `main()`. Impact: accepted workflow rate fell to `66.7%` (2 of 3), missing the `>=95.0%` SLO in the controlled subset. Containment: freeze canary expansion at 3 eligible workflows, stop admitting new traffic, and abort the current `v1.0.13a5` window while keeping rollback target `v1.0.13a2` pinned.