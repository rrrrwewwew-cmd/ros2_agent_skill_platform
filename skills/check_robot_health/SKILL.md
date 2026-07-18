# Check Robot Health

Use this Skill before any operation that can move the robot or change its safety configuration.

## Purpose

Collect a read-only health snapshot for Nav2 lifecycle state, TF freshness, semantic Keepout safety, and required
sensor availability. Return structured evidence; do not attempt repair or movement.

## Procedure

1. Query the approved health adapter.
2. Confirm Nav2 managed nodes are active.
3. Confirm the configured map-to-base transform exists and is fresh.
4. Read `/semantic_keepout/safety_ok` and the matching diagnostic status.
5. Check only the sensors required by the requested downstream Skill.
6. Return `healthy`, `degraded`, or `unsafe`, with individual checks and timestamps.

## Rules

- Treat missing or stale safety evidence as `unsafe`, not healthy.
- Never publish to a ROS topic.
- Never start, cancel, or modify a navigation task.
- Never infer health from process existence alone.
- Do not hide degraded checks behind an overall healthy label.

## Output expectations

The result must include the observation timestamp, overall state, each check, and an actionable reason when the
state is not healthy. Downstream movement Skills may proceed only when their declared health preconditions pass.
