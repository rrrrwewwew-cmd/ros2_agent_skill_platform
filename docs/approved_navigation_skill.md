# 受批准导航 Skill：`navigate_to_approved_pose`

`navigate_to_approved_pose@0.1.0` 是项目二第一个会产生物理运动的标准 Skill。它的目标不是让
Agent 获得“自由控制机器人”的能力，而是把一次已经预览、已经人工批准的 Nav2 目标变成一个
有边界、可取消、可审计、不可重放的受控动作。

当前发布状态为 `UNIT_TESTED`，尚未完成真实 rbot 仿真验收、发布签名和 `ACTIVE` 激活。因此
Agent Runtime 目前不会执行它；真实仿真通过后才会继续 Registry 生命周期。

## 为什么必须增加一次性执行批准

已有三个 Skill 都是只读能力。只读 Skill 的版本审批证明“这段工具代码允许被调用”，但不能
证明“人类允许机器人此刻去这个位置”。运动 Skill 因而需要两种不同的批准：

1. **发布批准**绑定 Skill 版本和 artifact hash，回答“这个实现能否进入 Registry”；
2. **执行批准**绑定完整 invocation，回答“这个目标能否在这一次 run 中执行”。

执行批准保存在 SQLite Registry v2 的 `execution_approvals` 表中。它绑定
`approval_id`、`run_id`、`trace_id`、Skill 名称/版本、artifact hash 和全部输入的 canonical
SHA-256。有效期限制为 1～300 秒，Runtime 在进入动作 adapter 前通过事务原子消费。任何参数
变化、过期、重复使用、run 不一致或拒绝决定都会 fail closed。

Runtime 状态路径为：

```text
VALIDATING -> WAITING_APPROVAL -> EXECUTING -> VERIFYING -> SUCCEEDED
                    |                 |             |
                    +---------------> FAILED <-----+
```

批准在 `EXECUTING` 前就被消费，所以进程崩溃或动作结果未知时也不会自动重放。后续重试必须使用
新的 `run_id`、`trace_id`、`approval_id`，重新预览并重新人工批准。

## 固定执行边界

Skill 仅允许固定 adapter 使用以下 ROS 接口：

- 只读 topic：`/diagnostics`、`/semantic_keepout/safety_ok`、`/tf`、`/tf_static`、`/odom`、`/scan`；
- service：Nav2 生命周期、全局代价地图以及 NavigateToPose cancel；
- action：`/compute_path_to_pose` 与 `/navigate_to_pose`；
- topic 写权限为空，明确禁止 `/cmd_vel`。

Agent 不能传 planner id、behavior tree、topic 名称、namespace、地图文件或任意命令。它只能提供
范围受限的 map 目标、固定 `rbot_water_puddle_v2` profile，以及人工看到的两个预览 hash。

## 三层安全校验

### 1. 执行前

固定 adapter 重新采集机器人健康、TF、激光雷达、Keepout safety、语义地图、全局代价地图和
Nav2 路径。新路径 SHA-256 与语义地图 SHA-256 必须和批准时的预览完全一致；Keepout 中心必须
仍为 lethal cost，路径必须保持正净空。只有全部成立时才发送一个 NavigateToPose goal。

### 2. 执行中

adapter 持续读取 `/semantic_keepout/safety_ok`、`/odom` 和 map 到机器人 TF。safety 变为 false
或 95 秒内部超时会请求取消；Runtime 的 120 秒外层超时还会调用固定 cancel helper，避免只杀死
子进程却留下 Nav2 goal。

### 3. 执行后

进程退出码不是成功证据。结果还必须同时满足：Nav2 `STATUS_SUCCEEDED`、error code 为 0、位置
误差不超过 0.25 m、朝向误差不超过 15°、轨迹未进入 Keepout、safety 全程为 true，以及机器人
线速度不超过 0.03 m/s、角速度不超过 0.05 rad/s。Runtime 再按结果 Schema 和后置条件二次验证。

## 当前自动化证据

- `colcon build --symlink-install`：6 个包成功；
- `colcon test`：115 项测试，0 error、0 failure、0 skipped；
- 隔离 ROS Domain 无 Nav2/TF/传感器测试：返回 `unavailable`，`goal_accepted=false`、
  `motion_command_sent=false`；
- Registry 已迁移到 schema v2，并验证批准单次消费、过期、参数篡改、run 绑定和 v1 数据库迁移；
- artifact hash：`24c2dca959382b9a4db1fed850577a42172403322dd5225eeee50f562ea6865a`。

以上只证明确定性实现和 fail-closed 路径，不能替代下一步真实仿真。

## 仿真验收与受治理执行顺序

第一次真实仿真属于 Skill 作者测试，只能由人工操作员在隔离 rbot 仿真中直接运行固定 ROS
adapter。先运行 `preview_safe_route`，将它输出的新鲜 `route.path_sha256` 与
`keepout.source_content_sha256` 填入命令，再运行：

```bash
ros2 run robot_controlled_navigation_skills navigate_to_approved_pose \
  --goal-x 4.5 --goal-y 0.0 --goal-yaw-deg 0.0 \
  --keepout-profile rbot_water_puddle_v2 \
  --approved-path-sha256 <fresh_path_sha256> \
  --approved-semantic-map-sha256 <fresh_semantic_map_sha256> \
  --ros-args -p use_sim_time:=true
```

仿真成功且证据冻结后，才依次进入 `SIMULATION_TESTED`、发布审批、Ed25519 签名和 `ACTIVE`。
激活后的正常 Agent/Runtime 路径必须使用一次性批准：

```bash
ros2 run robot_skill_registry skill_registry \
  --db ~/.ros/robot_agent/registry.db approve-execution \
  --invocation ~/robot_agent_ws/examples/navigate_to_approved_pose_invocation_v1.json \
  --actor human_li --reason "Approve the exact simulated east goal" \
  --ttl-sec 120

ros2 run robot_skill_runtime skill_execute \
  --invocation ~/robot_agent_ws/examples/navigate_to_approved_pose_invocation_v1.json \
  --trusted-public-key ~/.ros/robot_agent/keys/release_ed25519.pub.pem \
  --use-sim-time
```

示例 invocation 中的 ID 和预览 hash 仅作格式示例。每次真实执行必须重新生成唯一 ID，并替换为
同一现场的新鲜预览 hash。
