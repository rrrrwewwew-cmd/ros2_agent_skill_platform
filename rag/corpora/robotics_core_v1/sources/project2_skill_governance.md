# 项目二 Skill 治理事实卡

## 不可变身份

Skill 由 name、version 和 artifact hash 唯一绑定。Runtime 只加载 Registry 中 ACTIVE 的精确版本，
重新计算 artifact hash，并验证 Ed25519 发布 envelope；模型给出的名称或 hash 不能替代本地事实源。

## 权限与输入

每个 Skill 声明 safety level、输入 JSON Schema 和 ROS permissions。只读 Agent catalog 当前只暴露
`check_robot_health`、`query_semantic_target` 和 `preview_safe_route`；不能发布 `/cmd_vel`，也不能
调用任意 shell、任意文件或任意 ROS graph 接口。

## 受控运动

`navigate_to_approved_pose` 是 controlled Skill。它要求一次性 execution approval，并把已预览路径
hash、语义地图 hash、目标和动态安全前置条件绑定在一起。当前 MiMo Planner 不可见该 Skill；只读
Agent Loop 只调用 `/compute_path_to_pose`，不会调用 NavigateToPose。

## 证据门控

Tool 调用成功只代表契约有效，不代表环境安全。健康结果必须 `safe_to_proceed=true`，语义查询必须
`found=true`，安全路径必须 `safe_to_execute=true`；中间证据不通过时后续 Tool 不得运行。
