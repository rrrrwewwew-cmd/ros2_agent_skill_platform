# rbot live simulation evidence

`rbot_live_simulation_v1.json` is the operator-captured result of
`check_robot_health@0.2.0` against the project-one
`rbot_dynamic_semantic_keepout.launch.py` stack.

The required sensors were `/scan`, `/camera/image`, and
`/camera/depth_image`. The run confirmed active Nav2, current map-to-base TF,
matching semantic Keepout topic and diagnostic evidence, and fresh messages
from all three sensors. The result conforms to
`schemas/robot_health_result.schema.json`.

This evidence supports promotion to `SIMULATION_TESTED`; it is not human
approval, a release signature, or authorization to activate the Skill.
