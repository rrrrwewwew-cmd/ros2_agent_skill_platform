# 实验日志诊断 Agent 契约

## 1. 用例

用户可以提出“找出这次导航为什么发生抖动”一类问题。系统必须先建立可复算证据，再生成原因
假设，不能让 LLM 直接浏览文件后凭印象回答。

冻结工作流：

1. 查询实验目录并选择 `run_id`；
2. 校验 manifest、source hash、时间单位和坐标系；
3. 调用 Python 计算轨迹距离矩阵及时间序列特征；
4. 找出异常时间段；
5. 按时间戳关联机器人控制指令、位姿、Nav2、TF 和 diagnostics；
6. 使用 RAG 检索版本匹配的 ROS 文档、项目接口和历史失败，形成可能原因；
7. 生成 SVG 图表、结构化 JSON 和 Markdown 实验报告。

## 2. 证据分层

- `observation`：日志直接记录的值；
- `derived_metric`：由冻结算法和参数计算的指标；
- `anomaly_window`：满足公开阈值的时间区间；
- `hypothesis`：由证据支持但尚未通过干预实验证明的解释；
- `unknown`：当前数据不足以判断的部分。

报告禁止把时间相关性写成确定因果。每个 hypothesis 必须列出支持和反对证据，并包含工具版本、
参数、输入 artifact hash、Trace id 和 RAG source id。

## 3. 首版数据源

首版统一处理：

- 机器人位姿或里程计：时间戳、位置、朝向、线速度和角速度；
- 控制指令：目标线速度与目标角速度；
- Nav2：任务状态、恢复行为、规划和控制器事件；
- TF：查询失败、数据过期、跳变和时间外推；
- diagnostics：组件健康、安全状态和错误信息；
- Agent Trace：检索、计划、工具调用、审批和状态迁移。

所有时间戳在进入分析前转成整数纳秒。跨源关联必须记录实际时间差和允许容差。

## 4. 首版异常候选

确定性分析器至少产生以下候选，不直接宣布根因：

- 指令有运动但观测位移很小：`commanded_motion_without_progress`；
- 角速度指令短时间反复变号：`angular_command_oscillation`；
- 相邻位姿出现不合理跳变：`pose_discontinuity`；
- 异常窗口内恢复计数增长：`nav_recovery_activity`；
- TF/diagnostics 同期异常：`localization_or_tf_evidence`。

## 5. MCP 与权限

诊断工具默认 `read_only`。MCP Server 只接受工作区 allowlist 内的 `run_id`，不接受任意路径，
也不提供 Python `eval`、Shell 或任意 ROS topic 订阅。报告写入独立 artifact 目录，不覆盖原始日志。

## 6. 验收

- 冻结正例能命中标注异常窗口；
- 正常 run 不产生高严重度异常；
- 控制关联结果包含时间差且不超过配置容差；
- 同一输入和配置重复运行生成相同 JSON/SVG；
- 缺失、损坏、时间倒退或 hash 不一致的数据 fail closed；
- 报告能从 manifest 和 Trace 完整复算。
