# Preview Safe Route

Use this Skill to ask Nav2 for a global path and verify the returned geometry against one approved semantic Keepout
profile. It never sends `NavigateToPose`, publishes velocity, or moves the robot.

## Procedure

1. Validate the bounded map-frame goal and fixed `keepout_profile`.
2. Read and hash the approved persistent semantic risk record.
3. Verify that the risk-zone center is lethal in Nav2's current global master costmap.
4. call `/compute_path_to_pose` with `use_start=false`, so Nav2 uses the current robot TF pose.
5. Measure every path segment against the semantic zone, not only the sampled path poses.
6. Verify that the path ends within 0.25 m of the requested goal.
7. Return a typed result with `motion_command_sent=false`.

## Rules

- A returned path is not automatically safe.
- Missing planner, costmap, semantic-map, clock, or path evidence fails closed.
- The Keepout center must have global cost `>=253` and the path must not intersect the semantic zone.
- The result is only a preview; a later controlled navigation Skill must revalidate health and safety before motion.
- Never expose a caller-supplied file, planner id, action name, service name, or ROS namespace.
