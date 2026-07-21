# Skill Card: preview_safe_route

| Field | Value |
| --- | --- |
| Version | 0.1.0 |
| Status | DRAFT |
| Safety level | read_only |
| Human approval | not required |
| Physical motion | none |

## Intended use

Validate a candidate goal before any controlled navigation Skill is considered. The initial version is bound to the
project-one rbot water-puddle semantic map and its validated 0.6 m Keepout policy.

## Trust boundary

Agent inputs contain only bounded coordinates and one profile enum. Runtime owns the subprocess, ROS endpoints, map
file, risk target, radius, timeout, result Schema, and semantic postconditions. The Skill calls a planning Action but
no motion Action.

## Known limitations

The preview is a snapshot, not a reservation. Dynamic obstacles, TF, costmaps, or semantic risk evidence may change
before navigation; the later controlled Skill must check them again. The first profile supports only
`rbot_water_puddle_v2`.
