# Governed semantic target query evidence

`governed_release_v1.json` freezes the release and Runtime validation of
`query_semantic_target@0.1.0` against two persistent semantic maps produced by
project one.

The repository evidence intentionally records source content hashes instead of
copying the mutable runtime maps. The Runtime traces remain append-only under
`~/.ros/robot_agent/traces/`; no private release key or full external map is
committed.
