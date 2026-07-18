# 项目二计划与验收标准

## 最终交付

项目二最终交付“RAG + ROS 2 Skill 自动编写 + Skill Registry + 安全 Agent 执行 + 系统化评测”
闭环。作品集结论必须来自冻结测试集和自动化报告，不以单次成功对话代替评测。

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

## Phase 1：Skill Registry 与安全状态机

交付：

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

验收：未经批准、版本不匹配、前置条件失败或参数越界的 Skill 调用全部无法进入执行层。

## Phase 2：版本化 RAG

交付：

- ROS 2 Jazzy/Nav2/本地接口文档采集；
- 文档版本、source id 和 hash；
- 混合检索与引用输出；
- Skill 选择、故障诊断和代码编写三类查询；
- RAG 评测集和无 RAG 对照。

最低评测规模：30 个查询，覆盖正确文档、错误发行版干扰、项目一接口、TF/QoS/Lifecycle 故障
和 Skill 选择。报告 Recall@K、版本命中率、引用正确率和接口幻觉率。

## Phase 3：受控 Skill 自动编写

交付：

- ROS 2 Python/C++ 模板；
- 契约、实现、launch、参数和测试生成；
- 隔离 build sandbox；
- 编译/测试错误自动修复，设置最大轮数；
- 人工 diff 审批和 Registry 晋级。

最低评测规模：10 个 Skill 需求。报告首次/修复后编译成功率、单元/隐藏测试通过率、仿真通过率、
违规权限生成率、平均修复轮数和人工接受率。

## Phase 4：项目一能力接入

交付：

- Nav2 与安全监控 Tool adapter；
- 语义地图查询 Skill；
- 水坑风险观察与动态 Keepout 组合 Skill；
- 正常完成、取消、超时和 fail-closed 场景。

验收：Agent 能在不直接控制速度的情况下完成“检查风险—更新约束—规划—导航—验证”；项目一
感知失败、TF 过期或 safety false 时机器人不开始/继续危险任务。

## Phase 5：Agent 安全执行评测

最低 24 个场景：

| 类型 | 数量 | 目标 |
| --- | ---: | --- |
| 正常任务 | 6 | 任务完成和 Skill 组合 |
| 模糊/无效任务 | 6 | 澄清、拒绝和参数保护 |
| 恶意/注入任务 | 6 | 权限、Prompt Injection 和绕过企图 |
| 运行时故障 | 6 | TF、Nav2、感知、安全状态和超时 |

核心指标：任务成功率、计划 schema 通过率、违规调用拦截率、安全误拒绝率、实际不安全执行数、
紧急停止成功率/延迟、平均 Skill 调用数、墙钟时间和重复运行一致性。

安全硬门槛：测试集中实际不安全动作执行次数必须为 0。若未达到，不发布“安全执行”结论。

## Phase 6：A/B 与作品集交付

三组对照：

1. 无 RAG vs 有 RAG；
2. 原子 Tool Calling vs 复合 Skill；
3. 自由代码生成 baseline vs 受控生成流水线（仅 sandbox）。

交付 README、架构图、Skill 生命周期图、冻结 Trace、自动化报告、简历表述和面试手册。项目不以
演示视频为必需交付物。

## 明确不做

- 在线生成任意代码后直接控制机器人；
- 直接 `/cmd_vel`；
- 任意 Shell、文件和 ROS 图访问；
- 多 Agent、VLA、语音、开放 Web 搜索；
- 新地图和新仿真地形；
- 模型训练、多机器人和真实硬件部署。
