# Skill Card: check_robot_health

| Field | Value |
| --- | --- |
| Version | 0.1.0 |
| Status | DRAFT |
| Safety level | read_only |
| Human approval | not required |
| Source | project-two Phase 0 reference Skill |

## Intended use

Run before controlled/high-impact robot Skills to collect current Nav2, TF, sensor, and semantic-safety evidence.

## Non-goals

This Skill does not repair nodes, publish velocity, activate lifecycle nodes, change masks, or cancel navigation.

## Known limitations

The Phase 0 package defines and validates the contract but does not yet implement the ROS health adapter. Runtime
implementation and launch integration belong to Phase 1.

## Evaluation

The initial evaluation set covers a healthy snapshot, stale TF, and missing safety evidence. Promotion beyond
`DRAFT` requires the Phase 1 ROS adapter and integration tests.
