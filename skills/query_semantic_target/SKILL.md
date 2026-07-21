# Query Semantic Target

Use this Skill to read one canonical landmark from a previously observed project-one semantic map.

## Purpose

Return a typed, hash-backed snapshot containing the target position, uncertainty, observation counts, and latest
perception evidence. This Skill never starts perception, changes the map, plans a route, or moves the robot.

## Procedure

1. Select one approved `map_profile`; never accept a caller-provided file path.
2. Require a canonical manifest-allowlisted `target_id`.
3. Read the selected semantic map once and hash the exact bytes that were parsed.
4. Validate schema version, frame, counters, finite coordinates, uncertainty, timestamp, and evidence fields.
5. Return `found`, `not_found`, `unavailable`, or `invalid` with explicit evidence.

## Rules

- Do not resolve arbitrary aliases inside the execution boundary; natural-language resolution belongs to the later
  planner/RAG layer and must produce a canonical id.
- Do not expose `store_file` as an Agent input.
- Do not interpret `found` as permission to navigate.
- Do not hide malformed or missing evidence behind `not_found`.
- Do not write the semantic map or any ROS interface.

## Output expectations

For `found`, return the `map`-frame mean, sample standard deviation, accepted/rejected counts, timestamps, and last
perception evidence. The source content SHA-256 makes the answer replayable. A query can succeed as a tool call while
truthfully returning `not_found`, `unavailable`, or `invalid`.
