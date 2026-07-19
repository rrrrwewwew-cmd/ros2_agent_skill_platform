# 项目二当前进度检查点

更新时间：2026-07-19

本文件是休息、重启或上下文切换后的唯一恢复入口。恢复时先读本文件，再查看 Git 历史；不要
重新搭建项目一、重新选择地图，也不要重复实现或发布前四个 Skill。

## 当前结论

项目二仍严格沿着最初确定的“RAG 辅助 ROS 2 Skill 编写 + 受治理 Tool Calling Agent + 实验日志
诊断”路线推进。Phase 1 的前 4 个标准 Skill 已经完成受治理激活；真实 LLM API、RAG、MCP 和
Agent Loop 尚未开始。先完成确定性工具，是为了让后续模型只能调用已经有契约、权限、审批、
Trace 和物理后置条件的能力。

- 工作区：`/home/li/robot_agent_ws`
- Git 分支：`feature/skill-registry-state-machine`
- 第四个 Skill 实现提交：`d854b90 Add one-time approved navigation Skill`
- 首次运动仿真证据提交：`1c77006 Record approved navigation simulation evidence`
- 受治理发布证据提交：`853041b Record governed navigation release`
- 当前测试基线：115 项，0 error、0 failure、0 skipped
- 项目一与项目二仍是独立仓库；项目二仅通过已安装 ROS 2 接口复用项目一
- 当前 rbot 仿真可安全关闭，不存在需要保留的后台推理任务
- 当前成果只做本地保存，本检查点没有远端 push 或合并

## 已激活 Skill

| Skill | 版本 | 安全等级 | Registry 状态 | Artifact hash |
| --- | --- | --- | --- | --- |
| `check_robot_health` | `0.2.0` | `read_only` | `ACTIVE` | `1df7df2354693c025c850368661656c6014db9636c5b19914245c8ba26914e8f` |
| `query_semantic_target` | `0.1.0` | `read_only` | `ACTIVE` | `e4f6cddb16757bdee6b46163295152033a5f60a9aea7030fa5659eca2716200e` |
| `preview_safe_route` | `0.1.0` | `read_only` | `ACTIVE` | `d05c5c0aed6be59dbfb0f82c118b59099831c9c25db5c055fb56fb0326c7c7ca` |
| `navigate_to_approved_pose` | `0.1.0` | `controlled` | `ACTIVE` | `24c2dca959382b9a4db1fed850577a42172403322dd5225eeee50f562ea6865a` |

发布证据位于 `evidence/<skill>/governed_release_v1.json`。本机 release 公钥指纹为
`23ebcb2689b93221dec5de57e8a4344c54b9fbc63654ae16bef2a26634e36c8a`；私钥、Registry、execution
approval 和完整 Trace 位于 `~/.ros/robot_agent/`，不会进入 Git。

## 第四个 Skill 已完成的安全链路

`navigate_to_approved_pose@0.1.0` 是第一个会产生物理运动的受控 Skill，已完成：

1. 独立 ROS 2 包 `robot_controlled_navigation_skills`，未修改第三个已签名 artifact；
2. 固定 NavigateToPose adapter，只读 safety/TF/里程计/激光证据，禁止 topic 写入和 `/cmd_vel`；
3. 运动前重跑健康检查和路径预览，路径与语义地图 SHA-256 必须匹配人工批准内容；
4. 运动中监控 Keepout safety，unsafe 或内部超时会取消 Nav2 goal；
5. 运动后验证 Nav2 状态、终点误差、未进入 Keepout、全程 safety 和最终停止；
6. Registry schema v2 的一次性执行批准，绑定完整 invocation，TTL 限制 1～300 秒；
7. Runtime 状态 `WAITING_APPROVAL`，事务消费批准，参数篡改、run 不匹配、过期和重放均拒绝；
8. 隔离 ROS 图无 Nav2/TF/传感器时返回 `unavailable` 且不发送目标；
9. 6 个包构建成功，115 项自动测试全部通过；
10. rbot 首次作者仿真到 `(4.5,0,0°)` 成功，终点误差 0.044 m，未进入水坑；
11. 经显式人工发布批准、Ed25519 签名和独立验签后进入 `ACTIVE`；
12. 正式 Runtime run `navigate_home_active_001` 使用 120 秒一次性批准返回原点成功。

正式 Runtime 验证结果：

- Agent state：`SUCCEEDED`；Trace：13 个事件；
- 状态链包含 `WAITING_APPROVAL → EXECUTING → VERIFYING → SUCCEEDED`；
- approval `approval_navigate_home_active_001` 已由同名 run 原子消费，不能复用；
- 路径 hash 与语义地图 hash 在动作前重新计算并完全一致；
- Keepout 中心 cost：254；最小中心距离：0.889 m；进入禁区：否；
- 最终位置误差：0.044 m；朝向误差：13.264°；safety 全程正常；机器人已停止。

详细设计和冻结证据：

- `docs/approved_navigation_skill.md`
- `evidence/navigate_to_approved_pose/rbot_live_simulation_v1.json`
- `evidence/navigate_to_approved_pose/governed_release_v1.json`

## 下次唯一主线：第五个标准 Skill

开始设计并实现 `observe_and_avoid_water_risk`，不要跳到 LLM/RAG/MCP，也不要重复测试第四个
Skill。它应复用项目一已经完成的 GroundingDINO → Qwen-VL → RGB-D map 投影 → 语义地图 →
动态 Keepout 链路，但必须通过项目二的固定 adapter、Registry、Trace 和后置条件治理。

设计时先冻结：

1. 这是复合受控 Skill，负责“观察风险并建立/确认约束”，不能直接发布速度；
2. 感知事件必须保留 GroundingDINO candidate、Qwen semantic-policy、RGB-D/TF 投影和时间戳证据；
3. 只有风险被接受、地图投影有效且语义地图成功写入时，才允许进入下一阶段；
4. 必须验证新 Keepout 已在 global costmap 中达到 lethal cost，safety monitor 当前有效；
5. 感知失败、TF 过期、VLM 输出不一致、地图写入失败或 filter 未生效时 fail closed；
6. 需要明确它是否只观察和更新约束，还是组合第 3/4 Skill 完成绕行；优先保持可审计的分层组合；
7. 先完成确定性 adapter、Schema、单元测试和隔离 ROS 图测试，再进行真实仿真和发布。

第 5 个 Skill 完成后再实现：

6. `return_home_safely`

六个标准 Skill 全部完成后进入 Phase 2 版本化 RAG，再进入 Phase 3 的 LLM API、Prompt Registry、
MCP 与有界 Agent Loop。

## 恢复检查

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source install/setup.bash
git status -sb
colcon test-result --verbose

ros2 run robot_skill_registry skill_registry \
  --db ~/.ros/robot_agent/registry.db show \
  --name navigate_to_approved_pose --version 0.1.0
```

预期：Git 工作区干净、115 项测试通过、第四个 Skill 为 `ACTIVE`。随后直接开始
`observe_and_avoid_water_risk` 的契约设计。
