# 项目二计划与验收标准

## 最终交付

项目二最终交付“实验日志诊断 + RAG + MCP Tool Calling + ROS 2 Skill 自动编写 + Skill Registry
+ 安全 Agent 执行 + 系统化评测 + 可复现部署”闭环。作品集结论必须来自冻结测试集和自动化
报告，不以单次成功对话代替评测。

## Phase 0：架构与契约冻结

交付：

- 独立仓库和 ROS 2 工作区；
- 架构、安全边界和项目计划；
- `skill.schema.json`；
- 一个标准只读 Skill；
- 最小 `safe_agent_core` 包、验证器、测试和 CI。

验收：

- 项目一和项目二没有源码混合；
- 示例 Skill 可以通过 CLI 验证；
- 直接写 `/cmd_vel` 的 manifest 被拒绝；
- `colcon build/test` 与 GitHub CI 通过。

## Phase 1：实验证据、Registry 与确定性分析底座

交付：

- 实验 run manifest、Agent Trace 和分析报告 Schema；
- pose/control/Nav2/TF/diagnostics 时间序列的统一时间戳模型；
- 实验日志查询、距离矩阵、异常窗口检测和控制指令关联 Python 工具；
- 确定性 SVG/JSON/Markdown 报告；
- Registry 数据模型和状态迁移；
- artifact hash、版本和审批记录；
- 运行时 Agent 状态机；
- JSONL Trace 和离线 Replay；
- 6 个手写标准 Skill。

首批 Skill：

1. `check_robot_health`；
2. `query_semantic_target`；
3. `preview_safe_route`；
4. `navigate_to_approved_pose`；
5. `observe_and_avoid_water_risk`；
6. `return_home_safely`。

验收：冻结抖动样例可从原始时间序列自动找出异常窗口、关联控制命令并生成可复算报告；未经
批准、版本不匹配、前置条件失败或参数越界的 Skill 调用全部无法进入执行层。确定性工具输出
只描述证据与候选机制，不宣称已经证明因果关系。

当前已完成的 Phase 1 切片：

- hash 绑定的实验 manifest、Agent Trace、距离矩阵、异常窗口与确定性报告；
- SQLite Skill Registry、不可变版本、审批/签名治理事件；
- 持久化 Agent run、合法状态迁移、乐观并发检查和重启 fail-closed。
- `check_robot_health@0.2.0` 确定性策略、只读 ROS 适配器、结果 Schema 和隔离 ROS 图测试。
- `robot_skill_runtime` ACTIVE 状态、artifact hash、输入 Schema、ROS 权限、超时、结果与 Trace 门控。
- Ed25519 artifact 发布 envelope、独立验签登记和 Runtime 执行前二次验签。
- `query_semantic_target@0.1.0` 固定 map profile、单次字节快照 hash、严格证据验证和 Runtime adapter；已通过 77 项测试、完成 Ed25519 发布并进入 `ACTIVE`。
- `preview_safe_route@0.1.0` 固定规划 Action/代价地图 Service、目标范围、语义风险 profile、路径线段净空与 Runtime 后置条件；已通过 95 项测试和真实 rbot 无运动验证，完成 Ed25519 发布并进入 `ACTIVE`。
- `navigate_to_approved_pose@0.1.0` 固定 NavigateToPose adapter、路径/语义地图 hash 绑定、Registry 一次性执行批准、运行中取消与物理后置条件；已通过 115 项测试、隔离 ROS 图 fail-closed、真实 rbot 往返导航和 13 事件 Runtime Trace 验证，完成显式人工发布批准与 Ed25519 发布并进入 `ACTIVE`。

六个标准 Skill 均已有真实实现：前四个已完成发布签名并处于 `ACTIVE`；后两个项目一复合 Skill
已具备固定 adapter、Schema、测试、manifest 和 artifact lock，但仍保持候选，等待总验收、人工
diff 审批、Ed25519 签名和现场 ROS 回归。该状态是治理要求，不是缺少实现。

## Phase 2：版本化 RAG

交付：

- ROS 2 Jazzy/Nav2/本地接口文档采集；
- 文档版本、source id 和 hash；
- 混合检索与引用输出；
- Skill 选择、故障诊断和代码编写三类查询；
- RAG 评测集和无 RAG 对照。

最低评测规模：30 个查询，覆盖正确文档、错误发行版干扰、项目一接口、TF/QoS/Lifecycle 故障
和 Skill 选择。报告 Recall@K、版本命中率、引用正确率和接口幻觉率。

当前 Phase 2 的检索晋级切片已完成：`robot_rag@0.2.0`、13 个版本化来源、41 个 chunk、
feature-hash baseline、固定 revision 的 BGE-M3 dense provider、BM25+dense 混合排序、双分数门、
unknown identifier 拒答、hash-bound citations 和 A/B 评测器。20-case development 上两者均为
20/20；从未运行的 10-case holdout v3 只运行一次，BGE-M3 为 10/10、baseline 为 8/10，候选
no-answer 100%、接口幻觉 0。首次 learned v1 的失败结果仍保留，已揭盲数据已降级为回归集。

这满足当前 30-query 检索门和 learned-vs-deterministic A/B，但 10 条 holdout 仍是小样本，不能
外推为生产准确率。Phase 2 尚缺“无 RAG 对照下的最终回答质量”；该对照将在 Phase 3 的 MCP 诊断
Agent 中连同引用忠实度和无证据因果断言率一起评测。

## Phase 3：LLM API、Prompt Registry、MCP 与 Agent Loop

交付：

- Xiaomi MiMo LLM API、隔离 HTTP 边界和 deterministic fake test provider；
- Prompt Registry：版本、hash、输入/输出 Schema、评测和回滚；
- 具有严格 JSON Schema 的 MCP Server 与 Tool adapters；
- 有界 Tool Calling Agent Loop 和持久化状态；
- “查询日志—Python 分析—异常时间段—控制关联—原因假设—图表报告”完整诊断 Agent；
- Prompt Injection、越权工具调用、循环、超时和 Provider 故障测试。

验收：Agent 的每个结论能追溯到 Trace、工具输出和 RAG source id；MCP 不能绕过 Skill Registry、
审批和 ROS 权限；达到步骤、工具调用或时间上限时必须终止并保存可 Replay Trace。

Phase 3 的代码闭环已完成：MiMo plan-only Gateway、Prompt Registry、只读机器人 Agent Loop、
`robot_diagnosis_mcp@0.1.0` 五工具 stdio，以及 MiMo 诊断专用 Prompt 和固定
`list → inspect → analyze → retrieve → report` 状态机。正常、缺数据、注入、错误因果、Provider/Tool
超时和有/无 RAG 已进入冻结评测；真实 MiMo 诊断现场回归仍作为发布前外部验收，不由 CI 伪造。

## Phase 4：受控 Skill 自动编写

交付：

- ROS 2 Python/C++ 模板；
- 契约、实现、launch、参数和测试生成；
- 隔离 build sandbox；
- 编译/测试错误自动修复，设置最大轮数；
- 人工 diff 审批和 Registry 晋级。

最低评测规模：10 个 Skill 需求。报告首次/修复后编译成功率、单元/隐藏测试通过率、仿真通过率、
违规权限生成率、平均修复轮数和人工接受率。

当前实现已完成：版本化 RAG、结构化 MiMo 草案、确定性 ROS 2 Python renderer、AST/文件权限扫描、
无 shell 构建 sandbox、最多两轮修复、Registry 逐级晋级和 hash-bound 人工审批 CLI。冻结 10 需求
评测会真实构建 6 个合法候选并确定性拒绝 4 个越权需求；任何候选都不能自动进入 `ACTIVE`。

## Phase 5：项目一能力接入

交付：

- Nav2 与安全监控 Tool adapter；
- 语义地图查询 Skill；
- 水坑风险观察与动态 Keepout 组合 Skill；
- 正常完成、取消、超时和 fail-closed 场景。

验收：Agent 能在不直接控制速度的情况下完成“检查风险—更新约束—规划—导航—验证”；项目一
感知失败、TF 过期或 safety false 时机器人不开始/继续危险任务。

当前实现已完成两个固定复合 adapter：`observe_and_avoid_water_risk` 与 `return_home_safely`。两者
复用项目一安装态 Grounded-VLM/语义地图接口和项目二四个原子 adapter，使用一次外层精确审批，
并把实时 path/map hash 传入导航。候选发布状态将在最终测试与现场回归后推进。

## Phase 6：Agent 安全执行与诊断评测

最低 24 个场景：

| 类型 | 数量 | 目标 |
| --- | ---: | --- |
| 正常任务 | 6 | 任务完成和 Skill 组合 |
| 模糊/无效任务 | 6 | 澄清、拒绝和参数保护 |
| 恶意/注入任务 | 6 | 权限、Prompt Injection 和绕过企图 |
| 运行时故障 | 6 | TF、Nav2、感知、安全状态和超时 |

核心指标：任务成功率、计划 schema 通过率、违规调用拦截率、安全误拒绝率、实际不安全执行数、
紧急停止成功率/延迟、平均 Skill 调用数、墙钟时间和重复运行一致性。诊断指标另含异常窗口
precision/recall、控制关联正确率、证据引用正确率、无证据因果断言率和报告复算一致性。

安全硬门槛：测试集中实际不安全动作执行次数必须为 0。若未达到，不发布“安全执行”结论。

## Phase 7：A/B、作品集与可复现部署

三组对照：

1. 无 RAG vs 有 RAG；
2. 原子 Tool Calling vs 复合 Skill；
3. 自由代码生成 baseline vs 受控生成流水线（仅 sandbox）。

交付 README、架构图、Skill 生命周期图、冻结 Trace、自动化图表与报告、简历表述和面试手册。
同时交付锁定依赖、ROS 2 launch、MCP Server、RAG 索引命令、Agent API、健康检查、CI 和版本化
Release。项目不以演示视频为必需交付物。

当前已提供 42 场景冻结总评测、10 需求真实 Skill Author 门控、统一 CSV/JSON/Markdown/SVG 报告、
依赖锁文件、环境示例和一次性 `scripts/final_verify.sh`。2026-07-21 总验收已通过：14 个包、229 个
代码测试、10/10 Skill Author 和 42/42 策略场景。真实 MiMo 诊断、两个复合 Skill 现场成功闭环、
人工发布审批/签名以及一次性执行审批重放拦截均已有独立现场证据，不用确定性 replay 冒充。

## 明确不做

- 在线生成任意代码后直接控制机器人；
- 直接 `/cmd_vel`；
- 任意 Shell、文件和 ROS 图访问；
- 多 Agent、VLA、语音、开放 Web 搜索；
- 新地图和新仿真地形；
- 模型训练、多机器人、真机安全认证和生产现场无人监管上线。
