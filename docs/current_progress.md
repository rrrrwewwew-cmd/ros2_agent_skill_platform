# 项目二当前进度检查点

更新时间：2026-07-18

本文件是休息、重启或上下文切换后的唯一恢复入口。恢复工作时先读本文件，再查看对应的设计文档和 Git 历史；不要重新搭建项目一、重新选择地图，或重复已经完成的前三个 Skill。

## 当前结论

项目二仍沿着最初确定的“RAG 辅助 ROS 2 Skill 编写 + 受治理 Tool Calling Agent + 实验日志诊断”路线推进。当前完成的是 Phase 1 的确定性、安全治理底座，尚未接入真实 LLM API、RAG、MCP 或自由形式 Agent Loop。

- 工作区：`/home/li/robot_agent_ws`
- Git 分支：`feature/skill-registry-state-machine`
- 本检查点建立前的最新提交：`7a4d023 Record governed route preview release`
- 测试基线：95 项，0 error，0 failure，0 skipped
- 项目一与项目二保持独立仓库；项目二只通过已安装 ROS 2 接口复用项目一
- 当前没有需要继续运行的仿真或推理服务
- 当前成果仅保存在本地，本检查点不包含远端上传或合并

## 已完成的核心底座

1. 冻结实验样例可自动完成日志读取、距离矩阵、异常窗口、控制指令关联、SVG 图表和 Markdown/JSON 报告。
2. SQLite Skill Registry 已实现不可变版本、状态迁移、审批/签名事件与持久化 Agent run。
3. Skill Runtime 已实现固定 adapter、输入 Schema、ROS 权限、超时、结果后置条件、Trace 与 Replay 门控。
4. Artifact file lock 与 Ed25519 发布 envelope 已实现；Runtime 会在调用前重新计算 hash 并二次验签。
5. 三个标准只读 Skill 已完成真实 ROS 验证、签名发布与受治理激活。

## 已激活 Skill

| Skill | 版本 | Registry 状态 | Artifact hash |
| --- | --- | --- | --- |
| `check_robot_health` | `0.2.0` | `ACTIVE` | `1df7df2354693c025c850368661656c6014db9636c5b19914245c8ba26914e8f` |
| `query_semantic_target` | `0.1.0` | `ACTIVE` | `e4f6cddb16757bdee6b46163295152033a5f60a9aea7030fa5659eca2716200e` |
| `preview_safe_route` | `0.1.0` | `ACTIVE` | `d05c5c0aed6be59dbfb0f82c118b59099831c9c25db5c055fb56fb0326c7c7ca` |

对应受治理发布证据：

- `evidence/check_robot_health/governed_release_v1.json`
- `evidence/query_semantic_target/governed_release_v1.json`
- `evidence/preview_safe_route/governed_release_v1.json`

本机 release 公钥指纹：`23ebcb2689b93221dec5de57e8a4344c54b9fbc63654ae16bef2a26634e36c8a`。私钥、Registry 数据库和运行 Trace 位于 `~/.ros/robot_agent/`，不进入 Git。

## 第三个 Skill 的最新真实验证

`preview_safe_route@0.1.0` 已在项目一 rbot headless 仿真栈中通过 Runtime 调用，对目标 `(4.5, 0.0)` 进行无运动路径预览：

- Nav2 路径点：173
- 路径长度：5.1134813433 m
- `water_puddle` 中心代价值：254
- 语义禁区半径：0.600 m
- 路径到禁区中心最小距离：0.9823659811 m
- 扣除半径后的最小净空：0.3823659811 m
- 路径进入禁区：否
- 目标终点误差：0.000 m
- 机器人运动：否；调用后里程计速度接近零
- Runtime Trace：11 个事件，执行与后置条件均通过

这证明第三个 Skill 只读取规划与代价地图证据，不发送导航目标，也不直接控制机器人。

## 下次唯一主线

开始实现第四个标准 Skill：`navigate_to_approved_pose`。它将是项目二第一个受控物理动作 Skill，不应跳到 LLM/RAG/MCP，也不要先做第五或第六个 Skill。

实现前必须冻结以下安全契约：

1. 风险等级为 `controlled`，每次执行必须具备显式人工批准证据。
2. 只能通过固定 Nav2 `NavigateToPose` adapter 执行，禁止直接写 `/cmd_vel`，禁止任意 ROS graph 访问。
3. 输入目标必须通过 Schema、地图范围和参数边界检查。
4. 执行前重新运行机器人健康与语义 Keepout 安全检查，并绑定新鲜的 `preview_safe_route` 结果；应考虑使用预览结果 hash/目标摘要防止批准后参数被替换。
5. 必须支持超时、取消、Nav2 失败和 safety false 的 fail-closed 路径。
6. 必须验证导航结果、终点误差、Keepout 未进入和机器人最终停止，再允许 run 成功结束。
7. 先完成确定性 adapter、单元测试、隔离 ROS 图测试和仿真证据，再进入 Registry 审批、Ed25519 签名和 `ACTIVE`。

后续仍按既定顺序完成：

5. `observe_and_avoid_water_risk`
6. `return_home_safely`

六个标准 Skill 完成后，再进入 Phase 2 的版本化 RAG，以及 Phase 3 的 LLM API、Prompt Registry、MCP 与有界 Agent Loop。这样 LLM 调用的是已经有契约、权限、证据和回放能力的工具，而不是直接控制 ROS。

## 恢复检查

下次开始时执行：

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source install/setup.bash
git status -sb
colcon test-result --verbose
```

预期结果：位于本检查点提交之后的干净分支，测试仍为 95 项全通过。随后阅读 `docs/skill_contract.md`、`docs/skill_runtime.md` 与 `docs/route_preview_skill.md`，开始第四个 Skill 的契约设计。
