# 项目二系统架构

## 1. 目标

项目二构建一个面向 ROS 2 移动机器人的 Agentic Skill 平台。它同时解决三个问题：

1. LLM 如何利用版本正确、可引用的机器人知识；
2. 如何把自然语言需求转成可测试、可审批的 ROS 2 Skill；
3. 运行时 Agent 如何在确定性安全边界内选择和执行 Skill。

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
        └───────────────────┘
```

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
