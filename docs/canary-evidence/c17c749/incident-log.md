# Incident Log - c17c749

Status: held

## 2026-05-11T10:02:33Z - code_validation incident on anthropic baseline

- batch: `canary_c17c749_smoke04`
- provider/scenario: `anthropic` / `baseline`
- severity after policy review: `SEV1`
- classification: `code_validation`
- public symptom: generated code artifact was not found
- terminal outcome: `failed`
- immediate canary impact: cumulative state moved to `9/10` accepted workflows at the 10-workflows checkpoint, with `1` incident and `0` rollbacks
- containment: a fresh-root targeted replay of the same provider/scenario pair (`canary_c17c749_smoke04_retry`) passed cleanly at `2026-05-11T10:03:21Z`
- policy review at `2026-05-11T10:20:20Z`: cumulative state remained `10/11` accepted (`90.91%`), below the `>=95.0%` accepted-workflow target; retained non-accepted share (`9.09%`) exceeded both the `5.0%` budget and the `>50%` early-window burn rule
- immediate action after policy review: freeze further canary admission on `c17c749`, preserve the retained evidence bundle, and block same-candidate retry until root cause documentation and an explicit retry decision exist
- rollback posture: rollback target `89d6e138bc5ff582c9fd2e8b31ec2e2b954c2bbc` / `v1.0.13a12` remains the safe baseline; no continuously routed traffic required an environment switch in this maintainer-operated smoke canary