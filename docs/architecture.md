# 项目二系统架构

## 1. 目标

项目二构建一个面向 ROS 2 移动机器人的 Agentic Skill 平台。它同时解决四个问题：

1. LLM 如何利用版本正确、可引用的机器人知识；
2. 如何把自然语言需求转成可测试、可审批的 ROS 2 Skill；
3. 运行时 Agent 如何在确定性安全边界内选择和执行 Skill；
4. 如何让 Agent 基于可复算实验日志定位异常并生成有证据的诊断报告。

系统的安全目标不是保证 LLM 永远不提出错误动作，而是保证错误计划和未经批准的代码不能到达
机器人执行层。

## 2. 总体数据流

```text
                         ┌──────────────────────────┐
                         │ Versioned RAG Knowledge  │
                         │ ROS / Nav2 / local APIs  │
                         │ failures / policies      │
                         └────────────┬─────────────┘
                                      │ cited context
                  ┌───────────────────┴───────────────────┐
                  │                                       │
        ┌─────────▼─────────┐                   ┌─────────▼─────────┐
        │ Runtime Planner   │                   │ Offline Skill     │
        │ existing skills   │                   │ Author            │
        └─────────┬─────────┘                   └─────────┬─────────┘
                  │ structured plan                        │ generated package
        ┌─────────▼─────────┐                   ┌─────────▼─────────┐
        │ Plan Validator    │                   │ Build Sandbox     │
        │ policy + schema   │                   │ build/test/sim    │
        └─────────┬─────────┘                   └─────────┬─────────┘
                  │ approved calls                         │ human approval
        ┌─────────▼─────────┐                   ┌─────────▼─────────┐
        │ Safe Skill Runtime│◄──────────────────│ Skill Registry    │
        │ ROS 2 executor    │    active skills  │ versions/signing  │
        └─────────┬─────────┘                   └───────────────────┘
                  │
        ┌─────────▼─────────┐
        │ Project-one ROS 2 │
        │ Nav2/perception/  │
        │ semantic safety   │
        └─────────┬─────────┘
                  │ typed results
        ┌─────────▼─────────┐
        │ Trace + Evaluator │
        │ Python Analytics  │
        └───────────────────┘
```

LLM 不直接读取任意文件或调用 Python。LLM API 只接收经过检索和脱敏的上下文，所有分析、ROS
访问和报告生成都通过具有 JSON Schema 的 Tool Calling。MCP 是工具发现与调用协议层，不替代
Registry、策略校验或 ROS 2 执行安全边界。

## 3. 控制面与数据面

### 3.1 运行时控制面

运行时只加载 `ACTIVE` Skill。Agent 输出结构化计划，Validator 检查：

- Skill 是否在 Registry；
- 版本和 hash 是否匹配；
- 输入是否符合 schema；
- 当前状态是否满足前置条件；
- 权限和人工确认是否满足；
- 最大步骤、超时和循环限制；
- Nav2、TF 和 safety monitor 是否健康。

计划通过后，Executor 在每一步执行前重新检查动态前置条件，而不是只在计划生成后检查一次。

### 3.2 离线工程面

如果 Registry 中没有所需能力，运行时任务应失败并报告 `SKILL_NOT_AVAILABLE`。用户可以另行
启动 Skill Author：RAG 提供文档、模板、现有接口和安全规则；LLM 在隔离目录生成代码、契约和
测试；只有完整通过构建、测试、仿真和人工审批后才能晋级 `ACTIVE`。

运行时与离线生成必须是两个独立进程和权限域。

## 4. Skill 生命周期

```text
DRAFT
  → GENERATED
  → STATIC_VALIDATED
  → BUILT
  → UNIT_TESTED
  → SIMULATION_TESTED
  → HUMAN_APPROVED
  → SIGNED
  → ACTIVE
  → DEPRECATED
```

任何失败状态都不能跳过中间阶段。重新生成代码、修改参数或更换依赖后，版本/hash 改变，必须
重新执行验证流程。

## 5. 安全状态机

```text
IDLE
  → RETRIEVING
  → PLANNING
  → VALIDATING
  → WAITING_APPROVAL
  → EXECUTING
  → VERIFYING
  → SUCCEEDED | FAILED | ABORTED
```

任意非终止状态都允许进入 `EMERGENCY_STOP`。停止操作不依赖 LLM，也不要求人工批准。

## 6. 权限分级

| 级别 | 示例 | 默认策略 |
| --- | --- | --- |
| read_only | 查询健康、位姿、地图、预览路径 | 自动执行 |
| controlled | 普通导航、风险观测 | 动态安全检查后执行 |
| high | 更新语义地图、启停安全策略 | 需要人工确认 |
| emergency | 取消任务、停止 | 随时允许 |

Skill manifest 声明所需 ROS topic/service/action 权限。执行进程后续使用 SROS2 enclave 做第二层
通信权限限制，防止单靠应用层白名单失效。

## 7. RAG 边界

首版知识库只包含版本化、可追溯来源：

- ROS 2 Jazzy 和 Nav2 文档快照；
- 项目一 README、配置、接口和冻结失败记录；
- Skill schema、模板、Registry 和安全策略；
- 已批准 Skill 的说明、测试和评测结果。

运行时不进行开放 Web 搜索。检索结果必须包含 source id、版本、路径/URL 和片段 hash。传感器
文本与用户输入均视为不可信数据，不能作为系统指令注入。

首个 `robot_rag@0.1.0` 切片已经把该边界实现为 source manifest → 源文件 hash → 确定性 Markdown
分块 → chunk hash → canonical index hash → 发行版过滤 → 带引用检索。当前 BM25 + feature hash
只作为零外部模型的可复算 baseline；学习型 embedding 必须锁定模型 revision、维度和构建参数，并
与 baseline 在同一冻结评测集上 A/B，不能静默替换索引语义。

## 8. 代码生成边界

生成器只能从批准模板创建 ROS 2 包，依赖项受 allowlist 控制。生成代码在 sandbox 中运行，
禁止接触真实机器人 ROS domain、用户密钥和主工作区。最低晋级门槛：

- manifest 和 JSON Schema 通过；
- 静态检查通过；
- `colcon build` 通过；
- 单元和隐藏测试通过；
- `launch_testing` 正常退出；
- Gazebo 安全场景通过；
- 人工批准；
- artifact hash/签名生成。

## 9. 项目一集成边界

项目二只依赖项目一安装后的 ROS 2 接口。首批组合 Skill 将调用：

- Nav2 health、路径预览、导航、取消；
- 语义地图只读查询；
- Grounded-VLM 风险现场观测；
- 动态 Keepout；
- `/semantic_keepout/safety_ok` 与 `/diagnostics`；
- 导航结果和风险区净空验证。

项目二不复制或重新实现 GroundingDINO、Qwen-VL、RGB-D 投影和 Keepout 算法。

## 10. 实验诊断数据面

实验诊断是项目二的首个完整 Agent 用例，其确定性数据流为：

```text
实验目录/Trace
  → 查询 run 与校验 manifest/hash
  → 对齐 pose、control、Nav2、TF、diagnostics 时间戳
  → Python 距离矩阵与时间序列特征
  → 异常窗口检测
  → 关联控制指令和系统事件
  → RAG 检索 ROS 文档、历史失败与项目接口
  → LLM 生成有引用的原因假设
  → SVG/JSON/Markdown 实验报告
```

确定性工具只报告观测、阈值和候选机制，不能把相关性冒充因果性。LLM 必须区分 `evidence`、
`hypothesis` 和 `unknown`，每条原因假设都引用时间窗口、工具输出和 RAG source id。

首批 MCP Tool 规划为：

- `query_experiment_runs`；
- `load_ros_timeseries`；
- `compute_distance_matrix`；
- `detect_anomaly_windows`；
- `correlate_control_commands`；
- `retrieve_failure_knowledge`；
- `generate_experiment_report`；
- `request_skill_approval`。

## 11. LLM、Prompt、Agent 与状态边界

- 真实 LLM Provider 固定为 Xiaomi MiMo；deterministic fake 只用于无网络 CI，不是第二个线上 API；
- Prompt 存入 Prompt Registry，记录版本、hash、输入/输出 schema 和评测结果；
- Tool Calling 参数必须先通过 JSON Schema，再经过权限和运行时前置条件校验；
- Agent Loop 具有最大步骤、最大工具调用、墙钟超时、取消和失败终止条件；
- 会话、计划、审批、Skill 版本和 Trace id 持久化，进程重启不能绕过审批；
- Prompt、模型、检索结果、工具输入输出和状态迁移进入结构化 Trace，但密钥和敏感数据不落盘。

## 12. 可复现部署

作品集 v1 的部署目标是单机可复现环境：锁定 Python/ROS 依赖，提供 ROS 2 launch、MCP Server、
RAG 索引构建、Agent API、Registry/Trace 存储、健康检查、CI 和版本化 Release。真机安全认证、
生产现场高可用和无人监管运行属于后续工程，不作为 v1 结论。

## 13. Registry 持久化

Phase 1 使用 SQLite 作为单机事实源，详细契约见
[Skill Registry 与持久化 Agent 状态机](registry_state_machine.md)。Skill 的 `name + version`
不可覆盖，审批和签名绑定 artifact hash；所有写操作使用事务和 expected-state 检查。该层只管理
治理状态，不执行 ROS 动作。未来 MCP、LLM Planner 和 Executor 均不能绕过 Registry 直接加载
Skill。
