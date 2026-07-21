# navigate_to_approved_pose

Use this Skill only after `preview_safe_route` returned `safe` for the same goal and a human explicitly approved the exact governed invocation.

## Required workflow

1. Copy the path SHA-256 and semantic-map SHA-256 from the safe route preview into the controlled invocation.
2. Present the exact goal, Keepout profile, hashes, Skill version, and artifact hash to the human reviewer.
3. Store one expiring execution approval in the Registry. The approval must bind the full invocation and intended `run_id`.
4. Invoke the Skill through `robot_skill_runtime`; never call its ROS module directly from an Agent.
5. The fixed adapter repeats robot health, lidar, TF, semantic safety, costmap, and path checks immediately before motion.
6. It sends exactly one `/navigate_to_pose` goal only if the fresh path and semantic-map hashes still match the approved preview.
7. During motion it monitors semantic safety, odometry, and map pose. Unsafe evidence or timeout causes cancellation.
8. Success requires Nav2 success, goal tolerance, no Keepout entry, continuously safe monitoring, and a verified stopped robot.

## Prohibitions

- Never publish `/cmd_vel` or any equivalent base velocity topic.
- Never accept an unregistered action, service, topic, map path, behavior tree, planner id, or namespace from Agent input.
- Never reuse an approval: it expires and is consumed transactionally before the action call.
- Never retry automatically after an accepted goal, timeout, cancellation, crash, or failed postcondition.
- Never interpret tool-process success as navigation success; inspect the typed `state` and postconditions.
