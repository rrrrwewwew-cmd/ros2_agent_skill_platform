# MiMo + MCP 实验诊断 Agent

## 交付目标

`robot_diagnosis_agent@0.1.0` 把已有的五个诊断 MCP Tool 连接成一个持久化、可回放、失败关闭的
Agent Loop。MiMo 只负责产生结构化计划；实验文件读取、数值分析、RAG 检索和报告落盘均由固定
MCP Tool 完成。

## 固定证据顺序

```text
MiMo diagnosis plan
  → list_experiment_runs
  → inspect_experiment_run
  → analyze_experiment_run
  → retrieve_robotics_knowledge
  → materialize_diagnosis_report
  → deterministic conclusion
```

这五步不能删除、重排或替换。Prompt、JSON Schema 和本地 `validate_cross_step_plan` 同时验证工具
名称、版本、contract hash、连续 step id、实验 `run_id`，以及报告检索问题和前一步 RAG 问题的
一致性。LLM 即使返回合法 JSON，也不能更换证据对象或增加任意工具。

## 每步证据门

- 列表阶段：目标 `run_id` 必须存在于经过验证的实验目录；
- 检查阶段：manifest 中每个输入源必须有 SHA-256；
- 分析阶段：`source_hashes` 必须与检查阶段完全一致，并产出确定性 `analysis_sha256`；
- 检索阶段：必须有不可变 RAG index hash，并且“带 hash-bound citation”与“明确 abstain”二选一；
- 报告阶段：报告必须绑定分析 hash，同时返回 bundle 和逐文件 hash。

最终结论固定写入 `root_cause_proven=false`。系统可以给出候选机制，但相关性证据不能被包装成
已经证明的根因。

## 状态、超时与进程边界

Agent 使用 SQLite `AgentRunStore` 保存状态，使用 JSONL 保存父 Trace，并通过文件锁拒绝两个诊断
Agent 同时运行。启动时遗留的非终态 run 会被 fail-closed 恢复为终止状态。Agent 有总墙钟上限，
每次 MCP 调用也有独立上限。

官方 MCP 客户端运行在 `~/robot_agent_mcp_env`，服务端使用本地 stdio，不监听网络端口。学习型
RAG 单独运行在 `~/qwen_vl_env`，环境强制离线且不继承代理变量。MiMo API key 不进入子进程、
Trace 或报告。

隔离 RAG 的 `PYTHONPATH` 只包含仓库内 `robot_rag` 和 Ubuntu ROS 2 已声明的
`/usr/lib/python3/dist-packages`。后者提供 `python3-jsonschema`；不会继承当前交互 shell 中的其他
工作区路径，也不会因此获得网络、shell 或任意文件权限。

## 为什么不是让 LLM 自由循环

实验诊断的数学步骤具有已知依赖关系。自由 ReAct 循环会引入重复分析、跳过 hash 检查、在没有
证据时先写结论等风险。本实现保留 Agent 的自然语言规划能力，但把可执行状态空间压缩为一个
可证明的有向序列；这是机器人故障分析比通用聊天 Agent 更重要的工程取舍。
