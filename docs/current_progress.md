# 项目二当前进度检查点

更新时间：2026-07-21

本文件是休息、重启或上下文切换后的唯一恢复入口。恢复时先读本文件和 Git 历史；项目一与项目二
保持独立仓库，不要重建项目一，不要恢复已经取消的多 Provider、多 Agent 或演示视频路线。

## 当前结论

项目二的 v1 **代码闭环、现场验收和本地统一验收已经完成**。系统已经覆盖 LLM API、版本化 Prompt、结构化
Tool Calling、持久化 Agent Loop、Python 实验分析、版本化 RAG、官方 MCP stdio、可观测 Trace、
人工审批、受治理 Skill Author、项目一能力组合、冻结评测和单机可复现部署。

真实 MiMo 诊断、两个项目一复合 Skill 的现场仿真回归、人工 diff 审批、Ed25519 签名、`ACTIVE`
晋级、一次性执行审批与重放拦截均已完成。按最初作品集目标估算，当前约完成 **99%**；唯一剩余
工作是整理本批变更并完成 GitHub commit、push、PR/merge 和版本化 release，不再新增功能。

- 工作区：`/home/li/robot_agent_ws`
- Git 分支：`feature/skill-registry-state-machine`
- 最近已提交基线：`8da1bc4 Add governed experiment diagnosis MCP tools`
- 当前批量实现：尚未 commit/push/merge
- ROS 2 包：14 个
- JSON Schema：36 份
- 统一代码测试：229/229，0 error、0 failure、0 skipped
- Skill Author 冻结评测：10/10
- 最终冻结策略评测：42/42
- 实际不安全动作：0
- 生产 LLM：Xiaomi MiMo；`FakeProvider` 仅用于确定性 CI
- 默认机器人规划 Prompt：`robot_task_planner@0.2.0`
- 项目一通过安装态 ROS 2/Python 接口复用，未复制源码

统一验收命令：

```bash
cd ~/robot_agent_ws
scripts/final_verify.sh
```

机器报告位于：

- `~/.ros/robot_agent/skill_author_evaluation_v1/summary.json`
- `~/.ros/robot_agent/final_evaluation_v1/summary.json`
- `~/.ros/robot_agent/final_evaluation_v1/sample_results.csv`
- `~/.ros/robot_agent/final_evaluation_v1/report.md`
- `~/.ros/robot_agent/final_evaluation_v1/metrics.svg`

脱敏、hash 绑定的仓库证据位于
`evidence/final_evaluation/reproducible_policy_v1.json`。

## 已发布与候选 Skill

| Skill | 版本 | 安全等级 | 状态 | Artifact hash |
| --- | --- | --- | --- | --- |
| `check_robot_health` | `0.2.0` | `read_only` | `ACTIVE` | `1df7df2354693c025c850368661656c6014db9636c5b19914245c8ba26914e8f` |
| `query_semantic_target` | `0.1.0` | `read_only` | `ACTIVE` | `e4f6cddb16757bdee6b46163295152033a5f60a9aea7030fa5659eca2716200e` |
| `preview_safe_route` | `0.1.0` | `read_only` | `ACTIVE` | `d05c5c0aed6be59dbfb0f82c118b59099831c9c25db5c055fb56fb0326c7c7ca` |
| `navigate_to_approved_pose` | `0.1.0` | `controlled` | `ACTIVE` | `24c2dca959382b9a4db1fed850577a42172403322dd5225eeee50f562ea6865a` |
| `observe_and_avoid_water_risk` | `0.1.0` | `controlled` | `ACTIVE` | `3b4158d71f8b3485d2fb85fb59aed37af6e0c32387c96114c505008b763e916a` |
| `return_home_safely` | `0.1.0` | `controlled` | `ACTIVE` | `1c8968d1e246ac7ff371ee9a9985902265dfa3f6e4216863eb47b87ae00eca63` |

前四个 Skill 的发布证据位于 `evidence/<skill>/governed_release_v1.json`，两个组合 Skill 的共同
发布证据位于 `evidence/project1_composite/governed_release_v1.json`。本机私钥、Registry、执行批准
和完整 Trace 位于 `~/.ros/robot_agent/`，不会进入 Git。六个 Skill 当前均为 hash 绑定、签名并经
运行时二次验签的 `ACTIVE` 版本；两个 controlled 组合 Skill 每次运动仍须单独人工审批。

## 本轮一次性完成的技术路线

### 1. 通用 MiMo Gateway 与 Prompt 契约

- 将 Gateway 从单一机器人计划扩展为 Prompt 自带输出 Schema、允许 Skill/Tool catalog 和 hash pin；
- 新增诊断计划与 Skill Author 计划 Schema；
- 保留计划层和执行层隔离，模型输出必须经过 JSON Schema、本地 catalog 和 artifact pin 复核；
- 密钥仅从 `MIMO_API_KEY` 读取，不写入仓库、Trace 或子进程。

### 2. MiMo + MCP 实验诊断 Agent

- 新增 `robot_diagnosis_agent@0.1.0`；
- 强制执行 `list → inspect → analyze → retrieve → materialize`，模型不能增删或重排工具；
- 每步验证 run id、source hash、analysis hash、RAG citation/abstention 和报告 bundle hash；
- SQLite 持久状态、进程锁、墙钟/工具超时和 JSONL Trace 全部 fail closed；
- 结论固定区分“候选机制”与“已证明因果”，`root_cause_proven=false`。

详见 [diagnosis_agent.md](diagnosis_agent.md)。

### 3. 受治理 Skill Author

- 新增 `robot_skill_author@0.1.0`；
- MiMo 只生成受 Schema 约束的工作流草案，不生成可直接执行的任意源码；
- 源码由确定性 renderer 生成，随后经过请求策略、AST/文件权限、`compileall`、`colcon build`、
  pytest unit 和 simulation fixture；
- sandbox 不使用 shell，并删除 API key 与代理环境；最多允许两轮有界修复；
- 合法候选最多晋级 `SIMULATION_TESTED`，必须人工 diff 审批、签名和 adapter review 才能激活；
- 10 项评测中 6 个合法候选均首轮完成构建/单测/仿真，4 个 `/cmd_vel`、任意 shell、审批绕过和
  未知依赖请求全部拒绝，自动激活数为 0。

详见 [governed_skill_author.md](governed_skill_author.md)。

### 4. 项目一复合能力

- 新增 `robot_composite_skills@0.1.0`；
- `observe_and_avoid_water_risk` 固定组合健康检查、项目一 Grounded-VLM 现场观测、语义查询、
  Keepout 安全路径预览和带新鲜 hash 的受控导航；
- `return_home_safely` 固定组合健康检查、已有水坑语义地图查询、安全路径预览和受控返回；
- 复合 adapter 不能被 manifest entrypoint 直接绕过，只能经 `SkillExecutor`、Registry、artifact、
  一次性批准和运行时证据门执行。

详见 [project1_composite_skills.md](project1_composite_skills.md)。

### 5. 最终评测与部署

- 新增 `safe_agent_eval` 和 42 场景冻结总评测：24 个安全执行、8 个诊断、10 个生成治理；
- 输出 CSV、JSON、Markdown 和 SVG，输入清单与报告带 SHA-256；
- 三组 A/B：RAG vs 无 RAG、原子 vs 复合、受治理生成 vs 自由生成风险基线；
- 新增依赖锁、环境示例、部署说明和一次性 `scripts/final_verify.sh`；
- 14 包构建与 229 个代码测试全部通过；42/42 策略评测通过，故障 fail-closed 率 100%，违规
  拦截率 100%，无证据因果断言率 0，实际不安全动作 0。

详见 [final_evaluation_and_deployment.md](final_evaluation_and_deployment.md) 和
[final_retrospective.md](final_retrospective.md)。

## 已有真实现场证据

以下结论来自真实 MiMo、本地模型/MCP 或 rbot ROS 仿真，不与冻结 replay 混淆：

- MiMo API 冒烟成功：`mimo_smoke_003` 正确选择 `check_robot_health@0.2.0`；
- MiMo Prompt v0.1.0 六例基线 5/6，失败被保留；v0.2.0 路径定向回归 1/1；
- rbot 只读 Agent `agent_route_live_001` 成功执行 health → route preview，未发送运动命令；
- BGE-M3 在一次性 holdout v3 为 10/10，baseline 为 8/10；
- 官方 MCP 1.28.1 stdio 五工具、BGE-M3 引用、幂等报告和源日志不变验证通过；
- 真实 MiMo 诊断 Agent `diagnosis_live_mimo_002` 已完成五步闭环，2 条引用、19 个 Trace 事件，
  `root_cause_proven=false`；脱敏证据位于 `evidence/diagnosis_agent/`；
- 项目一复合 Skill 现场预检已通过 health 六项证据门，以及同步 RGB-D → GroundingDINO →
  Qwen2.5-VL 7B AWQ → 时间戳 TF 投影 → 语义地图更新；水坑定位 `(1.671, 0.007) m`，累计观测
  2 次，脱敏证据位于 `evidence/project1_composite/`；
- 现场预检发现并修复 `Path.resolve()` 解引用 `venv/bin/python`、导致模型子进程退回系统 Python 的
  环境边界错误；GroundingDINO/Qwen 两个解释器均保持 venv 身份，专项回归 6/6；
- 项目一 GroundingDINO → Qwen-VL 水坑识别、RGB-D 投影和动态 Keepout A/B 已由项目一独立保存。

这些证据位于 `evidence/`。冻结 42 场景不冒充真实模型或真实机器人结果；10 条 holdout 也不能
外推为开放世界 100% 准确率。

## 剩余发布收口

### 2026-07-21 组合 Skill 现场边界测试

- `observe_avoid_east_live_001` 在健康、现场 Grounded VLM 观测和语义查询通过后，因新建路径预览
  子进程尚未接收到首帧仿真 `/clock` 而失败关闭；没有发送运动命令。Runtime 已增加只针对精确
  `ROS clock is unavailable` 结果的三次有界重试，并修复“内部 aborted、外层却 SUCCEEDED”的
  状态映射。
- `observe_avoid_east_live_002` 完成健康检查、GroundingDINO → Qwen-VL、RGB-D 投影、语义地图
  更新、Keepout 路径预览和受控导航。路径未穿越禁区，实测最小中心距离 `0.943 m`，机器人停止
  在目标位置误差 `0.065 m` 内；但最终航向误差 `15.87°` 超过 Skill 合同的 `15°`，因此在 Nav2
  返回成功后仍被后置条件门判为 FAILED。没有为了通过测试放宽安全容差。
- `return_home_live_001` 的健康、语义查询与返程预览均通过，路径长度 `5.230 m`、最小语义净空
  `0.365 m`；导航子进程在发送目标前因冷启动节点的 `observed_at_ns=0` 抛出
  `RoutePreviewInputError`，确认没有发送运动命令。Runtime 现仅对这条可证明发生在 preflight 的
  精确异常执行最多三次、受原始 deadline 约束的重试；未知 `exit 1` 仍立即失败，并保留有界
  stderr 尾部用于诊断。
- 上述 Runtime 修复的安装态验收为 `robot_skill_runtime` 38/38；当前工作区累计测试结果为
  229 tests、0 errors、0 failures、0 skipped。修改未触及六个 ACTIVE Skill 的已签名 artifact。
- `return_home_live_002` 在新的精确一次性审批下完成真实返程闭环：审批由 `human_li` 签发并仅由
  同名 run 消费；预览与执行的路径哈希、语义地图哈希均一致，Keepout 中心代价为 `254`，规划
  最小净空 `0.365 m`，实测最小中心距离 `0.924 m`，未进入禁区且安全监视全程正常。最终位置
  误差 `0.085 m`、航向误差 `5.04°`、机器人停止，外层和内部状态均为 SUCCEEDED。
- `observe_avoid_east_live_003` 在返程后的 `174.96°` 朝向执行，健康检查通过，但相机背向水坑；
  GroundingDINO 候选的颜色占比、深度样本与传感器复核均为 0，级联在 grounding gate 返回
  `risk_found=false`，未调用 Qwen、未规划、未运动。这验证了负观测失败关闭，同时明确了当前
  `observe_and_avoid_water_risk@0.1.0` 的部署前置条件：机器人必须位于能直接观察目标风险的已知
  视点；本场景的标准起始姿态为原点 `yaw=0°`。
- `align_home_for_observation_001` 通过新的单次审批调用 `return_home_safely`，在原点完成面向水坑
  方向的姿态对齐；最终位置误差 `0.026 m`、航向误差 `11.96°`，机器人停止，安全监视正常，
  实测最小水坑中心距离 `1.620 m`。该结果恢复了观测组合 Skill 的标准现场前置条件。
- `observe_avoid_east_live_004` 中 GroundingDINO 与 Qwen 均确认水坑，但 `-11.96°` 的底盘终态使
  候选位于图像最左侧（方位约 `-41.79°`）。RGB-D 投影得到 `(2.716, 1.443) m`，与已验证地标
  的误差为 `1.611 m`，语义地图离群值门拒绝更新；组合因此未规划、未运动。这证明 VLM 正判
  不能绕过几何一致性门，也表明导航可接受的航向误差不等同于窄视场感知视点精度。最终现场
  观测应从仿真定义的标准初始姿态执行，后续版本再考虑显式的感知视点合同与更严格姿态对齐。
- 最终重启测试前通过只读 TF 核对标准初始视点：`map → base_footprint` 平移约
  `(0.000, 0.000) m`、RPY 航向 `0.000°`。后续最终组合调用以该现场前置条件为准，执行时仍由
  Skill 自身重新验证 Nav2、TF、传感器和语义 Keepout 安全状态。
- `observe_avoid_east_live_005` 从已验证的标准初始视点完成最终真实组合闭环：现场 GroundingDINO
  → Qwen 语义策略确认水坑，RGB-D 投影回到 `(1.671, 0.007) m`，地标累计 5 次接受、1 次离群
  拒绝；更新后的语义地图哈希在查询、预览和导航 preflight 中保持一致。规划最小净空
  `0.382 m`，实测最小中心距离 `0.949 m`，未进入禁区，安全监视正常；最终位置误差 `0.050 m`、
  航向误差 `13.88°`、机器人停止，外层和内部均为 SUCCEEDED。

按顺序执行，不再扩展范围：

1. **已完成**：经一次性精确 invocation 审批，两个复合 Skill 的现场成功链路分别由
   `return_home_live_002` 和 `observe_avoid_east_live_005` 证明；
2. **已完成**：`observe_avoid_replay_block_001` 使用新 run 故意重放已由
   `observe_avoid_east_live_005` 消费的审批，Registry 在 `WAITING_APPROVAL` 返回
   `execution approval has already been consumed`；Trace 中 `tool_call` 数量为 0，未进入感知、
   规划或运动；
3. **已完成**：2026-07-21 再执行 `scripts/final_verify.sh`，14 包构建成功、229 tests 全部通过、
   Skill Author 10/10、最终策略 42/42；
4. 更新最终证据索引、commit、push、PR/merge 和版本化 release。

项目 v1 不需要演示视频，也不继续制作地图、训练模型、加入 DeepSeek、模型投票、多 Agent、VLA、
任意 shell、直接 `/cmd_vel` 或生产真机安全认证。

## 恢复命令

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source install/setup.bash

git status -sb
colcon test-result --verbose

# 一次性本地总验收
scripts/final_verify.sh

# 真实诊断 Agent；要求当前 shell 已设置 MIMO_API_KEY
ros2 run robot_diagnosis_agent run_diagnosis_agent \
  --task '分析 jitter_demo_001 的异常时间段、控制关联和可能机制，生成有引用的报告' \
  --experiment-run-id jitter_demo_001
```
