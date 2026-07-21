# Skill card: return_home_safely@0.1.0

- Safety: controlled; exact one-time approval required.
- Inputs: bounded map pose and the fixed `rbot_water_puddle_v2` policy.
- Dependencies: health, semantic query, route preview and approved navigation adapters.
- Failure policy: first-error stop with evidence hashes and Nav2 cancellation support.
- Current release status: implementation candidate; human review, signature and activation remain explicit.
