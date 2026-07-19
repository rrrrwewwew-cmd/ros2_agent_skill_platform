# Skill Card: navigate_to_approved_pose

| Field | Value |
| --- | --- |
| Version | 0.1.0 |
| Safety level | controlled |
| Human approval | required for every invocation |
| Idempotent | no |
| Direct velocity | forbidden |
| Motion interface | fixed `/navigate_to_pose` Nav2 Action |

## Intended use

Execute one bounded map-frame pose goal after a signed `ACTIVE` release, an exact one-time human approval, and a fresh safe route revalidation. The initial profile is restricted to the project-one rbot water-puddle semantic Keepout.

## Safety case

The release approval proves that this artifact was reviewed; it does not authorize a specific motion. A separate execution approval binds the complete invocation, artifact hash, run id, and expiry. The Runtime consumes it exactly once. The ROS adapter then repeats health and route checks, compares the new path and semantic source hashes with the approved preview, monitors safety during motion, cancels on unsafe evidence, and validates final stop and geometry.

## Known limits

This is a simulation portfolio control boundary, not a certified safety controller. Pose sampling and ROS diagnostics complement but do not replace real-time hardware safety. No automatic retry is permitted because an accepted navigation goal is non-idempotent.
