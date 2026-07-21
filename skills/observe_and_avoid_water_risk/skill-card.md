# Skill card: observe_and_avoid_water_risk@0.1.0

- Safety: controlled; exact one-time approval required.
- Model role: GroundingDINO proposes a region and Qwen-VL applies the semantic policy.
- Deterministic authority: RGB-D projection, semantic-map hash, costmap Keepout and Nav2 results.
- Failure policy: fail closed at the first evidence mismatch; cancel is supported by the navigation adapter.
- Current release status: implementation candidate; human review, signature and activation remain explicit.
