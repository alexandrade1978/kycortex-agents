# Rollback Log - c17c749

Status: policy hold recorded

## 2026-05-11T10:20:20Z - expansion freeze and rollback-target retention

- candidate SHA / version: `c17c7492d3aded8d0dfcf84087cd9a77712dad33` / `v1.0.13b1`
- rollback target SHA / version: `89d6e138bc5ff582c9fd2e8b31ec2e2b954c2bbc` / `v1.0.13a12`
- trigger: the 10-workflows checkpoint missed the `>=95.0%` accepted-workflow target at `9/10`, and the retained replay still left the cumulative canary at `10/11`; the resulting non-accepted share exceeded the `5.0%` budget and crossed the `>50%` first-half burn rule
- decision owner: Alexandre Andrade
- immediate action: freeze further workflow admission on `c17c749`, retain the failing artifacts and telemetry, and keep `v1.0.13a12` as the safe baseline for any future rollback or replacement candidate comparison
- environment switch performed: no continuously routed traffic existed in this maintainer-operated smoke canary, so the rollback action was recorded as an expansion freeze rather than a live environment switch
- retry posture: do not resume `c17c749` until the root cause is documented and an explicit retry decision is recorded