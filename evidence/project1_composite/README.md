# Project-one composite live evidence

`live_grounded_observation_v1.json` records the repository-safe subset of the
2026-07-20 rbot live simulation preflight for
`observe_and_avoid_water_risk@0.1.0`.  The run exercised synchronized RGB-D,
GroundingDINO, Qwen2.5-VL 7B AWQ semantic policy, timestamped TF projection and
the persistent semantic landmark update.  Raw RGB-D/model artifacts remain in
the local evidence directory and are referenced only by SHA-256.

The preflight exposed and then verified a Python virtual-environment boundary
bug: resolving `venv/bin/python` symlinks selected `/usr/bin/python3.12` and
lost model dependencies.  The pipeline now makes interpreter paths absolute
without dereferencing them, with a dedicated regression test.

`governed_release_v1.json` records the explicit human approval, artifact
identities, Ed25519 verification and Registry activation of both composite
Skills.  It contains no private key or reusable execution approval.  Each
future motion run still requires a separate exact-invocation approval.
