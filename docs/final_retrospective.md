# 项目二 v1 技术复盘

## 项目是否仍符合最初规划

符合。最初目标不是做一个“会聊天的 ROS 助手”，而是交付一个能查询实验日志、调用 Python 分析、
定位异常时间段、关联控制指令、形成可审计原因假设、生成图表报告，并能通过 RAG/MCP/Skill
安全接入机器人的 Agent 平台。当前四个闭环与原计划一一对应：

1. 实验诊断：日志 → 确定性分析 → RAG 引用 → MCP 报告；
2. Skill 编写：需求 → RAG → 结构化草案 → 确定性代码 → 构建/测试/仿真 → 人工审批；
3. 安全执行：自然语言 → MiMo 计划 → Registry/签名/证据门 → 固定 adapter；
4. 系统评测：冻结场景 → Trace → 指标 → CSV/JSON/Markdown/SVG。

中途最重要的路线修正，是停止继续制作仿真地形，也没有让 LLM 直接控制机器人。项目一负责
Grounded-VLM、RGB-D、语义地图和 Nav2 Keepout；项目二通过安装态接口把这些能力治理成 Skill。
这样作品集体现的是 Agent 系统、机器人安全和工程评测能力，而不是场景美术。

## 分阶段技术决策

### 确定性安全底座先于 LLM

先实现 JSON Schema、SQLite Registry、不可变 artifact hash、Ed25519 发布、一次性执行批准、固定
adapter、Agent run 状态机和 JSONL Trace，再接 MiMo。原因是 LLM 的正确输出不能替代权限、版本、
证据新鲜度和动作后置条件。模型负责提出结构化意图，确定性系统决定能否执行。

### Prompt 与模型版本必须可追踪

Gateway 固定 provider、model、prompt id/version/hash、request hash、token 和延迟。Prompt v0.1.0
真实六例出现一次 Skill policy 失败后，没有覆盖历史版本，而是发布 v0.2.0，并在联网前加入逐 Skill
输入 Schema 门。这样失败样本、修复和回归之间具有可解释的版本链。

### RAG 的重点是版本和引用，不是“接了向量库”

语料由 source id、distribution、revision 和 SHA-256 绑定；检索结果必须返回 source/chunk hash 或
明确 abstain。BGE-M3 与确定性 baseline 做 development/holdout A/B，保留首次失败，不把 10 条
holdout 的 100% 写成开放世界准确率。MCP 的学习型检索运行在离线隔离子进程中。

### MCP 是窄工具协议，不是任意系统后门

诊断 MCP 只开放五个固定 Tool，分别列出、检查、分析、检索和物化报告。实验源目录和报告目录
分离，报告写入幂等，源日志 hash 在运行前后不变。诊断 Agent 又在 Prompt、Schema 和本地状态机
三层强制五步顺序，避免自由 ReAct 跳过证据或提前编造根因。

### Skill Author 采用“结构化生成 + 确定性渲染”

模型不能提交 Python 字符串。它只能选择已批准依赖并生成结构化工作流；renderer 生成固定 ament
Python 包，sandbox 执行静态检查、编译、`colcon build`、unit 和 simulation。候选最多到
`SIMULATION_TESTED`，不会自动签名或激活。这比展示一次自由代码生成更接近企业机器人系统的
供应链和变更治理要求。

### 项目一能力以复合 Skill 接入

两个复合 Skill 没有复制项目一源码，而是组合四个项目二原子 Skill 和项目一现场观测接口。外层
一次性批准减少用户确认点，内部仍保留健康、VLM/TF、语义地图、Keepout、路径 hash 和动作后置
条件。组合的便利性没有削弱原子安全边界。

## 最终验证结果

2026-07-21 执行 `scripts/final_verify.sh`：

- 14 个 ROS 2 Jazzy 包构建成功；
- 229 个单元、契约、静态和隔离集成测试全部通过；
- Skill Author 10/10：6 个合法候选首轮 build/unit/simulation 通过，4 个越权请求拒绝；
- 系统策略 42/42：安全执行 24/24、诊断 8/8、Skill Author 10/10；
- 故障 fail-closed、违规调用拦截和诊断顺序策略均为 100%；
- RAG citation rate 100%，无证据因果断言率 0；
- 自动激活候选 0，实际不安全动作 0。

一次性验收首次暴露两个代码风格问题和一个候选测试 `PYTHONPATH` 隔离问题。前者是未使用导入/
变量；后者表现为 6 个候选均能编译但测试无法导入生成包。修复方式是在无 shell sandbox 中只向
pytest 注入候选包根目录，不 source 任意脚本、不放宽权限。随后完整总验收重跑并通过。

## 证据边界与完成状态

冻结策略评测证明契约、状态机和故障路径按设计工作，但不能替代真实 MiMo 或 ROS 仿真。独立真实
证据已经覆盖 MiMo 计划与诊断 Agent、BGE-M3、MCP stdio、只读 Agent、项目一动态 Keepout、两个
复合 Skill 的现场成功闭环、人工发布链和已消费审批重放拦截。PR #2、Pull Request CI、合并后的
`main` CI 和 `v1.0.0` Release 均已完成。因此可表述为“项目二 v1 代码、现场验收、自动化评测与
版本发布完成”，仍不能表述为生产无人监管机器人已经上线。

## 招聘价值

该项目可以支撑机器人 Agent、具身智能平台、LLM 应用工程和 ROS 2 软件岗位，核心可讲：

- 如何把概率模型放在计划层，把控制权留给确定性执行层；
- 如何设计 Prompt/Schema/Tool/Skill 的版本与 hash 信任链；
- 如何用 MCP、RAG 和 Python 分析形成可追溯实验诊断；
- 如何通过 Registry、签名、审批、Trace 和 fail-closed 状态机治理机器人动作；
- 如何评测代码生成与安全 Agent，而不是只展示一次成功对话；
- 如何在两个独立 ROS 2 项目间通过安装态接口复用真实感知与导航能力。

项目二已通过 PR #2 合并到 `main`，发布提交为 `75ea77a`，正式版本为 `v1.0.0`。最初作品集范围
没有剩余必做项，可以作为完整求职作品集交付。更大数据集、真机认证、高可用部署和感知视点
合同属于后续可选演进，不改变 v1 已完成的结论。
