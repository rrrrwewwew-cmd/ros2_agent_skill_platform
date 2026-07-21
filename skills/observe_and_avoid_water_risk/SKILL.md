# Observe and Avoid Water Risk

Use this controlled composite Skill when the robot must refresh live water-puddle evidence before moving to a
goal. It composes only fixed, governed adapters.

## Evidence order

1. Check Nav2, TF, Keepout, lidar, RGB and depth freshness.
2. Run the fixed GroundingDINO → Qwen-VL semantic-policy observer and require a map update.
3. Read the persisted `water_puddle` landmark and its source hash.
4. Compute a Nav2 path and require positive semantic Keepout clearance.
5. Execute the exact preview-bound goal under the outer one-time human approval.

Any missing, stale, mismatched or unsafe intermediate result stops the workflow. The Skill never publishes
`/cmd_vel`, never invents a goal and never treats VLM text alone as motion authority.
