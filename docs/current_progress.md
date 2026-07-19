# 项目二当前进度检查点

更新时间：2026-07-19

本文件是休息、重启或上下文切换后的唯一恢复入口。恢复时先读本文件，再查看 Git 历史；不要
重新搭建项目一、重新选择地图，也不要重复实现第四个 Skill。

## 当前结论

项目二仍严格沿着最初确定的“RAG 辅助 ROS 2 Skill 编写 + 受治理 Tool Calling Agent + 实验日志
诊断”路线推进。当前正在完成 Phase 1 的第 4 个标准 Skill。确定性治理底座已经具备，真实 LLM
API、RAG、MCP 和 Agent Loop 尚未开始，这一顺序是为了让后续模型只能调用已经有契约、权限、
审批、Trace 和物理后置条件的工具。

- 工作区：`/home/li/robot_agent_ws`
- Git 分支：`feature/skill-registry-state-machine`
- 上一个恢复点：`44a5f3f Save project two progress checkpoint`
- 第四个 Skill 实现提交：`d854b90 Add one-time approved navigation Skill`
- 当前测试基线：115 项，0 error、0 failure、0 skipped
- 项目一与项目二仍是独立仓库；项目二仅通过已安装 ROS 2 接口复用项目一
- 当前没有需要继续运行的仿真或推理服务
- 当前成果只做本地保存，本检查点没有远端 push 或合并

## 已完成并激活的三个只读 Skill

| Skill | 版本 | Registry 状态 | Artifact hash |
| --- | --- | --- | --- |
| `check_robot_health` | `0.2.0` | `ACTIVE` | `1df7df2354693c025c850368661656c6014db9636c5b19914245c8ba26914e8f` |
| `query_semantic_target` | `0.1.0` | `ACTIVE` | `e4f6cddb16757bdee6b46163295152033a5f60a9aea7030fa5659eca2716200e` |
| `preview_safe_route` | `0.1.0` | `ACTIVE` | `d05c5c0aed6be59dbfb0f82c118b59099831c9c25db5c055fb56fb0326c7c7ca` |

对应发布证据位于 `evidence/<skill>/governed_release_v1.json`。本机 release 公钥指纹为
`23ebcb2689b93221dec5de57e8a4344c54b9fbc63654ae16bef2a26634e36c8a`；私钥、Registry 和 Trace
位于 `~/.ros/robot_agent/`，不会进入 Git。

## 第四个 Skill 的当前状态

`navigate_to_approved_pose@0.1.0` 已完成实现，Registry 状态为 `UNIT_TESTED`，artifact hash 为：

```text
24c2dca959382b9a4db1fed850577a42172403322dd5225eeee50f562ea6865a
```

已完成：

1. 新建独立 ROS 2 包 `robot_controlled_navigation_skills`，没有修改第三个已签名 Skill 的 artifact；
2. 固定 NavigateToPose adapter，只读安全/TF/里程计/激光证据，禁止 topic 写入和 `/cmd_vel`；
3. 运动前重跑健康检查和路径预览，并要求路径 SHA-256 与语义地图 SHA-256 和批准内容一致；
4. 运动中监控 Keepout safety，内部超时或 unsafe 时取消 Nav2 goal；
5. 验证 Nav2 状态、终点误差、朝向误差、未进入 Keepout、全程 safety 和最终停止；
6. Registry schema 升级到 v2，加入绑定完整 invocation 的一次性执行批准；
7. Runtime 对 `controlled/high` Skill 执行 `WAITING_APPROVAL`，事务消费批准并写入 Trace；
8. 批准支持 1～300 秒 TTL，参数篡改、run 不匹配、过期和重复使用全部 fail closed；
9. 隔离 ROS Domain 无 Nav2/TF/传感器测试返回 `unavailable`，且
   `goal_accepted=false`、`motion_command_sent=false`；
10. `colcon build` 成功，115 项自动测试全部通过。

详细设计见 `docs/approved_navigation_skill.md`。格式示例见
`examples/navigate_to_approved_pose_invocation_v1.json`。

## 为什么还不能称为完成或 ACTIVE

`UNIT_TESTED` 只证明契约、纯策略、Registry、Runtime、超时和离线 fail-closed 路径。它还没有在
项目一的 rbot 仓库仿真中真正发送目标并验证绕开水坑、到达目标、停止和完整结果。因此当前不应
做发布审批、Ed25519 签名或 `ACTIVE`，Runtime 也会拒绝 Agent 调用。

## 下次唯一主线：真实 rbot 仿真验收

### 1. 启动项目一仿真

```bash
cd ~/ros2_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch semantic_nav_eval rbot_dynamic_semantic_keepout.launch.py
```

不要单独启动基础入口 `semantic_nav_bringup/sim_rbot_warehouse_nav.launch.py`；它默认使用不含
costmap filter 的 `nav2_burger.yaml`，水坑中心 cost 会是 0。上面的复合入口才会加载
`nav2_burger_keepout.yaml`、动态 mask、filter info server 和 safety monitor。确认 Gazebo、Nav2、
AMCL、语义 Keepout 和 safety monitor 正常后再继续。

### 2. 在另一个终端生成同一现场的新鲜只读预览

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source install/setup.bash

ros2 run robot_navigation_skills preview_safe_route \
  --goal-x 4.5 --goal-y 0.0 --goal-yaw-deg 0.0 \
  --keepout-profile rbot_water_puddle_v2 \
  --ros-args -p use_sim_time:=true
```

记录输出里的 `route.path_sha256` 和 `keepout.source_content_sha256`。不要沿用示例 JSON 的旧 hash。

### 3. 仅在 Skill 作者仿真阶段运行固定动作 adapter

```bash
ros2 run robot_controlled_navigation_skills navigate_to_approved_pose \
  --goal-x 4.5 --goal-y 0.0 --goal-yaw-deg 0.0 \
  --keepout-profile rbot_water_puddle_v2 \
  --approved-path-sha256 <fresh_path_sha256> \
  --approved-semantic-map-sha256 <fresh_semantic_map_sha256> \
  --ros-args -p use_sim_time:=true
```

预期：`state=succeeded`、`goal_reached=true`、`entered_keepout=false`、
`safety_remained_ok=true`、`robot_stopped=true`。如果失败，先保存完整输出，不自动重试。

### 4. 仿真通过后的治理工作

冻结仿真证据并推进到 `SIMULATION_TESTED`，再做发布审批、Ed25519 签名与 `ACTIVE`。激活以后才
测试正常 Runtime 路径：先为完整 invocation 发放 120 秒一次性人工批准，再由 Runtime 执行并
检查 Trace 中的 `WAITING_APPROVAL`、批准消费和物理后置条件事件。

完成第四个 Skill 后仍按既定顺序实现：

5. `observe_and_avoid_water_risk`
6. `return_home_safely`

六个标准 Skill 完成后进入 Phase 2 版本化 RAG，再进入 Phase 3 的 LLM API、Prompt Registry、
MCP 与有界 Agent Loop。

## 恢复检查

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source install/setup.bash
git status -sb
colcon test-result --verbose
```

预期：第四个 Skill 已存在、Registry 为 `UNIT_TESTED`、115 项测试通过；随后直接进行上面的真实
rbot 仿真验收，不再重复写实现。
