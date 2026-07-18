# `check_robot_health` 只读健康 Skill

## 1. 数据流

```text
Nav2 is_active service ─┐
map → base TF ──────────┤
safety_ok + diagnostics ├─→ bounded ROS adapter → deterministic policy → typed result
allowlisted sensors ────┘
```

ROS 适配器只收集证据，不发布话题、不调用导航 Action、不改变 Lifecycle 状态。判定器是纯 Python，
因此同一证据与阈值总是产生相同结果，单元测试不依赖仿真是否在线。

## 2. 状态策略

- `unsafe`：Nav2 非 active、TF 缺失/过期、Keepout safety false、诊断缺失/过期或非 OK；
- `degraded`：安全证据正常，但下游任务声明的必要传感器缺失或过期；
- `healthy`：全部安全检查和必要传感器检查通过。

只有 `healthy` 的 `safe_to_proceed` 为 true。`degraded` 不等于机器人正在发生危险，但仍然阻止依赖
该传感器的后续 Skill。

## 3. 权限边界

`required_sensors` 只能从 `skill.yaml` 的枚举中选择。实现同时使用代码级 allowlist 校验，防止输入
参数把只读健康检查扩展成任意 ROS graph 读取工具。Nav2 只调用 `is_active`，不会自动激活节点。

## 4. 运行

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source install/setup.bash

ros2 run safe_agent_core check_robot_health --ros-args \
  -p use_sim_time:=true \
  -p required_sensors:="[/scan, /camera/image]"
```

退出码：`0=healthy`、`3=degraded`、`4=unsafe/adapter error`。完整 JSON 结果符合
`schemas/robot_health_result.schema.json`，可直接写入 Agent Trace，并由后续 Executor 作为运动前置条件。

## 5. 当前治理状态

版本为 `0.2.0`，完成纯策略单测和隔离 ROS graph 集成测试，但仍保持 `DRAFT`。在项目一完整仿真栈
验证后，才会按 `STATIC_VALIDATED → BUILT → UNIT_TESTED → SIMULATION_TESTED` 顺序推进 Registry。
