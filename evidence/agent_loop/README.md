# Agent Loop 现场证据

本目录只保存可审查、可提交的脱敏证据摘要。完整父/子结果、SQLite 状态和 JSONL Trace 保留在
`~/.ros/robot_agent/`，避免把本机运行状态、绝对环境细节或任何凭据写入 Git。

- `live_read_only_route_v1.json`：MiMo 在 rbot 仿真现场规划并执行
  `check_robot_health → preview_safe_route` 的首次真实只读闭环。

摘要记录原始文件的 SHA-256、事件数量、Prompt/Skill pin、确定性安全证据和明确的无运动结论。
