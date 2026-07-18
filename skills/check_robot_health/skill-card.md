# Skill Card: check_robot_health

| Field | Value |
| --- | --- |
| Version | 0.2.0 |
| Status | DRAFT |
| Safety level | read_only |
| Human approval | not required |
| Source | project-two Phase 0 reference Skill |

## Intended use

Run before controlled/high-impact robot Skills to collect current Nav2, TF, sensor, and semantic-safety evidence.

## Non-goals

This Skill does not repair nodes, publish velocity, activate lifecycle nodes, change masks, or cancel navigation.

## Implementation status

The Phase 1 implementation contains a deterministic policy evaluator, a bounded read-only ROS 2 adapter, a typed
result Schema, unit tests, and an isolated ROS graph integration test. The adapter reads the Nav2 lifecycle health
service, map-to-robot TF, semantic safety topic/diagnostic, and only manifest-allowlisted required sensor topics.

## Known limitations

The Skill does not diagnose root causes or repair failures. It remains `DRAFT` until it passes a project-one live
simulation run and the Registry governance gates. Topic freshness is evaluated in the node clock domain; a clock
or TF inconsistency therefore fails closed.

## Evaluation

The evaluation set covers a healthy snapshot, stale TF, missing safety evidence, missing required sensors, future
timestamps, sensor permission rejection, and a healthy isolated ROS graph. Promotion beyond `DRAFT` requires a
project-one live-stack simulation result.
