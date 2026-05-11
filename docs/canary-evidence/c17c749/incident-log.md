# Incident Log - c17c749

Status: open

## 2026-05-11T10:02:33Z - code_validation incident on anthropic baseline

- batch: `canary_c17c749_smoke04`
- provider/scenario: `anthropic` / `baseline`
- classification: `code_validation`
- public symptom: generated code artifact was not found
- terminal outcome: `failed`
- immediate canary impact: cumulative state moved to `9/10` accepted workflows at the 10-workflows checkpoint, with `1` incident and `0` rollbacks
- containment: a fresh-root targeted replay of the same provider/scenario pair (`canary_c17c749_smoke04_retry`) passed cleanly at `2026-05-11T10:03:21Z`
- current state: incident remains recorded for canary review; no rollback has been executed