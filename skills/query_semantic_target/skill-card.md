# Skill Card: query_semantic_target

| Field | Value |
| --- | --- |
| Version | 0.1.0 |
| Status | DRAFT |
| Safety level | read_only |
| Human approval | not required |
| Source | project-two Phase 1 project-one data adapter |

## Intended use

Retrieve persistent semantic landmark evidence before route preview, observation planning, or risk-policy selection.

## Non-goals

This Skill does not run GroundingDINO/Qwen-VL, resolve unrestricted natural language, modify a map, publish ROS data,
plan a route, infer that an old landmark still exists, or authorize navigation.

## Trust boundary

The Runtime adapter maps two symbolic profiles to fixed files under `~/.ros/semantic_nav_eval`. The Agent cannot pass
a path. The query reads and hashes one byte snapshot, validates the project-one schema-v1 fields, and normalizes only
bounded evidence into the result contract.

## Known limitations

The project-one store uses wall timestamps and simulation observation stamps from different clock domains. This Skill
therefore reports both but does not invent a cross-domain age. Freshness policy belongs to the downstream task. The
initial target allowlist covers the portfolio scenes and must be versioned to add targets.

## Evaluation

Tests cover found and absent landmarks, unavailable and malformed stores, inconsistent counters, non-finite values,
profile/path escape attempts, source immutability, fixed subprocess arguments, result Schema, and semantic
postconditions. Live validation uses both the original landmark map and the rbot water-puddle map.
