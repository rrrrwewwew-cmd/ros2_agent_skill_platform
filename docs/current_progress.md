# 项目二当前进度检查点

更新时间：2026-07-20

本文件是休息、重启或上下文切换后的唯一恢复入口。恢复时先读本文件，再查看 Git 历史；不要
重新搭建项目一、重新实现前四个 Skill，也不要恢复已经取消的“双 Provider”设计。

## 当前结论

项目二已完成确定性安全底座、真实 MiMo 接入、Prompt 评测、只读 Agent Loop 现场闭环、版本化
RAG 学习型 embedding A/B 晋级，以及实验诊断 MCP 五工具真实 stdio 垂直切片。生产 LLM 只使用
Xiaomi MiMo；`FakeProvider` 仅服务无网络 CI，不是第二个 API。当前 MCP 可完成 run 查询、hash
检查、Python 异常分析、BGE-M3 引用检索和幂等报告，但尚未接入 MiMo 诊断专用状态机。下一主线
是实现强制证据顺序的诊断 Agent Loop 与冻结评测。

- 工作区：`/home/li/robot_agent_ws`
- Git 分支：`feature/skill-registry-state-machine`
- 前四个 Skill：均已签名并处于 `ACTIVE`
- ROS 2 包：10 个
- 当前测试基线：199 项，0 error、0 failure、0 skipped
- LLM 真实后端：Xiaomi MiMo Chat Completions
- 当前默认 Prompt：`robot_task_planner@0.2.0`
- Prompt canonical SHA-256：
  `652ad2e5b64735aefaea747a02634fc68796db0354501eb523f579bd940107ff`
- 安装态 Fake Provider 冒烟：通过
- MiMo 真实 API 冒烟：通过；`mimo_smoke_003`，计划选择 `check_robot_health@0.2.0`
- MiMo v0.1.0 真实 6-case 基线：5 PASS / 1 FAIL / 0 error；失败已定位并保留
- v0.2.0 安装态 Fake 回归：6/6 PASS；逐 Skill 输入合约门控已通过单元测试
- v0.2.0 MiMo 路径定向回归：1/1 PASS；Skill 选择和四项输入全部正确
- `robot_agent_orchestrator@0.1.0`：13 项测试通过，含真实 Registry/签名/Runtime 集成
- MiMo+rbot 真实只读 Agent Loop：`agent_route_live_001` 成功；两步 gate 均通过，未发送运动命令
- `robot_rag@0.2.0`：13 来源、41 chunks、30 条 development/holdout 用例；BGE-M3 已通过晋级门
- `robot_diagnosis_mcp@0.1.0`：五个 Tool、两份 Schema、官方 MCP 1.28.1 stdio 回归已通过
- BGE-M3 MCP 路径：检索与报告各带 3 条 hash-bound citation，7 个源实验文件保持不变
- 项目一与项目二仍是独立仓库；项目二仅复用项目一安装后的 ROS 2 接口
- 当前成果仅本地保存，本检查点没有远端 push 或合并

## 已激活 Skill

| Skill | 版本 | 安全等级 | Registry 状态 | Artifact hash |
| --- | --- | --- | --- | --- |
| `check_robot_health` | `0.2.0` | `read_only` | `ACTIVE` | `1df7df2354693c025c850368661656c6014db9636c5b19914245c8ba26914e8f` |
| `query_semantic_target` | `0.1.0` | `read_only` | `ACTIVE` | `e4f6cddb16757bdee6b46163295152033a5f60a9aea7030fa5659eca2716200e` |
| `preview_safe_route` | `0.1.0` | `read_only` | `ACTIVE` | `d05c5c0aed6be59dbfb0f82c118b59099831c9c25db5c055fb56fb0326c7c7ca` |
| `navigate_to_approved_pose` | `0.1.0` | `controlled` | `ACTIVE` | `24c2dca959382b9a4db1fed850577a42172403322dd5225eeee50f562ea6865a` |

发布证据位于 `evidence/<skill>/governed_release_v1.json`。本机私钥、Registry、execution
approval 和完整 Trace 位于 `~/.ros/robot_agent/`，不会进入 Git。

## 已完成的 MiMo LLM Gateway

新增 `robot_llm_gateway@0.1.0`：

1. 真实 Provider 只有 `MimoProvider`，默认地址为官方 `/v1/chat/completions`；
2. 密钥只读取 `MIMO_API_KEY`，模型和账户地址可通过 `MIMO_MODEL`、`MIMO_BASE_URL` 覆盖；
3. 使用非流式 JSON object 输出、关闭 thinking、限制 token、温度和墙钟超时；
4. Prompt Registry 按 `id + version + canonical SHA-256` 精确解析；
5. 用户任务作为不可信 user JSON，与系统规则和 Skill catalog 分离；
6. 只向模型暴露前三个只读 ACTIVE Skill，导航 Skill 当前不可见；
7. 输出必须通过 Agent Plan JSON Schema，最多 6 步；
8. 每一步的 Skill name、version 和 artifact hash 再与冻结目录逐项复核；
9. v0.2.0 进一步逐步校验 Skill 输入 Schema 和连续 step id，错误 fail closed；
10. Prompt hash 变化、Provider 不匹配、HTTP/空响应/非 JSON、Schema 错误和 hash 伪造均 fail closed；
11. Gateway 只返回 plan，不导入或调用 `robot_skill_runtime`；
12. 6 个冻结 eval case 覆盖正常请求、运动越权、Prompt Injection 和缺少输入；
13. Fake Provider 安装态 CLI 冒烟通过；MiMo 真实 API 返回计划并通过全部本地门控；
14. 真实调用延迟 6522.272 ms，输入 964 tokens、输出 249 tokens、总计 1213 tokens；
15. 脱敏证据位于 `evidence/llm_gateway/mimo_plan_only_smoke_v1.json`。

## 已完成的 Prompt 评测器

新增 `evaluate_robot_planner` 命令和两份机器契约：

- `schemas/prompt_evaluation_manifest.schema.json`
- `schemas/prompt_evaluation_summary.schema.json`

6 个冻结用例现在显式区分预期 decision、必须出现的 Skill 和允许出现的 Skill。评测器按清单顺序
串行调用，默认 Provider 首次失败立即停止；每个成功结果独立保存，重启后按 provider、model、
Prompt pin 和 request id 复核后续跑。汇总指标包含 Schema 成功率、decision 准确率、Skill policy
准确率、Prompt Injection 拒绝率、总/平均延迟和 token usage。

安装态 Fake Provider 评测已完成：6/6 PASS，四项比例指标均为 100%，证明评测和续跑机制可用；
Fake 结果不作为 MiMo 模型质量结论。Gateway 还会在联网前拒绝不适用于自定义后端的 `tp-`
Token Plan 凭据。

真实 `robot_task_planner@0.1.0` 基线已完成：5/6 PASS，Schema 成功率、decision 准确率和 Injection
拒绝率 100%，Skill policy 准确率 83.33%，平均延迟 9176 ms、总计 7159 tokens。唯一失败为路径
预览额外选择语义查询，并为该 Skill 编造坐标字段。证据冻结于
`evidence/llm_gateway/mimo_prompt_evaluation_v1.json`，分析见
`docs/mimo_prompt_evaluation_v1.md`。

修复没有篡改 v0.1.0，而是发布 `robot_task_planner@0.2.0`：Prompt catalog 现在包含精确输入 JSON
Schema，Gateway 对每一步本地 fail-closed 校验，并要求连续 step id；安装态 Fake v0.2.0 评测 6/6
PASS。完整工作区当前为 156 项测试通过。

v0.2.0 的真实定向回归也已通过：仅生成 `check_robot_health → preview_safe_route`，没有额外语义
查询；路径输入为 `(4.5, 0.0, 0.0, rbot_water_puddle_v2)`，Schema 与 Skill policy 均为 100%。
脱敏证据位于 `evidence/llm_gateway/mimo_prompt_v020_route_regression_v1.json`。

新增机器契约：

- `schemas/llm_plan_request.schema.json`
- `schemas/prompt_definition.schema.json`
- `schemas/agent_plan.schema.json`
- `schemas/llm_gateway_result.schema.json`

详细设计见 `docs/llm_gateway.md`。

## 已完成的只读 Agent Loop

新增第 8 个 ROS 2 包 `robot_agent_orchestrator@0.1.0` 和命令 `run_read_only_agent`。父级任务使用
持久状态机，MiMo 计划中的每一步使用独立子 run 进入原有 `SkillExecutor`。执行前再次限制只读
catalog、Skill pin 和最大步数；执行后使用确定性 evidence gate，而不是让 LLM 判断自身 Tool
Calling 是否成功。

已实现：

1. `plan / clarify / refuse` 三种决策的独立终态；
2. 顺序多步 Tool Calling 和首错停止；
3. 健康、语义目标和安全路径三类 evidence gate；
4. 父子 run、父子 JSONL Trace 和输入 SHA-256 关联；
5. 不安全中间证据立即 `blocked_by_evidence`，不调用后续 Skill；
6. 最后一步只读查询可如实返回 `safe_to_continue=false`，不误报 Runtime 失败；
7. 进程文件锁拒绝并发 Agent；拿到锁后才 fail-closed 恢复崩溃残留；
8. Agent Loop result JSON Schema；
9. 13 项测试，其中一项让 Fake LLM 计划真实穿过 ACTIVE Registry、Ed25519、artifact 校验和
   Runtime adapter。

详细设计与现场命令见 `docs/read_only_agent_loop.md`。

真实现场闭环 `agent_route_live_001` 已完成。MiMo 用时 9022.18 ms，生成
`check_robot_health → preview_safe_route`；健康证据确认 Nav2、TF 和语义 Keepout 正常，路径预览
生成 5.113 m / 173 pose 的安全路径。路径距水坑中心最小 0.982 m、净空 0.382 m，中心代价为
254，`motion_command_sent=false`。父 Trace 13 个事件，两个子 Trace 各 11 个事件；脱敏证据及原始
文件 hash 位于 `evidence/agent_loop/live_read_only_route_v1.json`。

本次运行也暴露了一个明确边界：健康 Skill 的 `required_sensors` 是可选输入，MiMo 本次传入空对象，
因此该证据覆盖 Nav2、TF 和 Keepout，但没有逐 topic 证明传感器新鲜度。后续安全执行评测前应把
关键传感器集合变成可信运行配置或强制输入，不能依赖 `expected_evidence` 自然语言字段。

## 已完成的版本化 RAG A/B

第 9 个 ROS 2 包已升级为 `robot_rag@0.2.0`：

1. `robotics_core@1.1.0` 含 13 个来源、41 个确定性 chunk，覆盖 ROS 2 Jazzy/Nav2、项目一接口、
   项目二 Gateway/Trace/诊断契约和一个 Humble 错版本干扰源；
2. manifest/source/chunk/index/profile 均由 SHA-256 绑定，路径穿越、字节变化、provider/维度冲突
   和索引篡改全部 fail closed；
3. 保留 bilingual BM25 + `feature_hash_v1` 作为无模型 CI/回滚 baseline；
4. 新增固定 revision 的 `BAAI/bge-m3` dense provider：1024 维、CLS pooling、L2 normalize；
5. learned policy 使用 BM25+dense、combined/embedding 双门和 unknown identifier 拒答；
6. 每个结果带原始/归一化 BM25、embedding、combined score 和 hash-bound citation；
7. 评测覆盖 Recall@K、MRR、版本过滤、引用完整性、answerability、no-answer 和接口幻觉；
8. development v2：baseline 与候选均 20/20；
9. 首次 learned v1 在旧 v2 评测中 8/10，失败证据保留，数据揭盲后降级为回归集；
10. learned v2 在揭盲回归集 10/10，在从未运行的 holdout v3 一次完成 10/10；baseline 在两组
    10-case 集均为 8/10；
11. holdout v3 候选 Recall@K/MRR/no-answer/版本/引用均为 100%，接口幻觉 0；baseline 的
    no-answer 为 50%、接口幻觉为 50%；
12. learned provider 是隔离的本地可选依赖，尚未接入 MCP/Agent 生产路径。

安装态 `robot_rag` 为 27 项测试通过；全仓 9 个包共 183 项测试通过，0 error、0 failure、
0 skipped。

10 条 holdout 的 100% 只能说明这组冻结样本通过，不能宣称开放世界准确率。设计与复算命令见
`docs/versioned_rag.md`；新脱敏证据位于 `evidence/rag/robotics_core_v2_bge_m3_ab.json`，旧 smoke
和失败历史均保留。

## 已完成的实验诊断 MCP 垂直切片

新增第 10 个 ROS 2 包 `robot_diagnosis_mcp@0.1.0`。该包不是任意文件或 Python 后门，而是在四个
信任根（experiment root、artifact root、RAG index、Schema directory）上配置的本地 stdio
Server：

1. `list_experiment_runs` 只列出 source hash 全部通过的 run；
2. `inspect_experiment_run` 返回 frame/time base 与逐源 hash；
3. `analyze_experiment_run` 调用确定性 Python，返回矩阵 hash、异常窗、控制证据和候选机制；
4. `retrieve_robotics_knowledge` 只允许三个 distribution、top-k≤3，并返回 citation 或 abstain；
5. `materialize_diagnosis_report` 只在独立 artifact root 幂等写 JSON/SVG/Markdown，不修改源日志。

协议层使用官方 `mcp==1.28.1` 稳定线、stdio transport 和结构化输出。四个查询工具 annotation 为
read-only/non-destructive/idempotent/closed-world；报告工具为 artifact-write/non-destructive/
idempotent/closed-world。所有输出通过 `mcp_tool_result.schema.json`，绑定 canonical input/evidence
SHA-256；报告再通过 `diagnosis_report_bundle.schema.json`。

BGE-M3 运行在固定 Qwen Python 的无 shell 子进程，Server 不加载模型。实现保留 virtualenv Python
符号链接，防止 `Path.resolve()` 悄悄退回系统解释器；子进程删除代理并强制 Hugging Face/
Transformers offline，只读取固定 revision 的本地缓存。这个修复把原先 120 秒网络等待恢复为约
6–9 秒查询。

验证：包级 16/16；deterministic stdio 五工具通过且正确 abstain；BGE-M3 stdio 五工具通过，
retrieval/report 各 3 条引用；两次运行的 7 个 source snapshot hash 均完全不变。证据位于
`evidence/mcp/`，详细路线、命令、故障复盘和边界见 `docs/diagnosis_mcp.md`。

本里程碑全工作区 10 个包已重新构建，`colcon test-result --verbose` 为 199 tests、0 errors、
0 failures、0 skipped。

## 架构决策修正

早期检查点要求先手写 `observe_and_avoid_water_risk` 和 `return_home_safely`，再接 LLM。经过架构
复盘后该顺序已废止：前四个 Skill 已经覆盖状态查询、知识查询、路径规划和受控动作四种最重要的
Tool Calling 形态，足以安全启动 Agent 层。第五、第六 Skill 将在后续 RAG + Skill Author 阶段
作为“模型辅助生成、构建、仿真、审批、签名、激活”的完整案例，而不是继续人工堆确定性工具。

这项修正不会降低安全性。模型当前只能规划三个只读 Skill；受控导航仍必须由已有 Runtime、一次性
approval、动态前置条件和后置条件处理。

## 下次唯一主线

1. 发布诊断专用 Prompt 与允许五个 MCP Tool 的精确输入 catalog；
2. 实现强制 `list → inspect → analyze → retrieve → report` 的持久化 Agent 状态机；
3. 每个步骤绑定 MCP input/evidence hash、RAG source/chunk hash 和 Agent Trace；
4. 使用 MiMo 做计划/假设表述，确定性工具继续掌握事实与计算，不让模型覆盖分析结果；
5. 冻结正常、缺数据、恶意注入和错误因果断言评测，再与无 RAG 对照；
6. 诊断 Agent 达标后进入 RAG-assisted Skill Author；受控导航仍不向模型开放。

不要在下一步增加 DeepSeek、模型投票、自动 Provider 切换或多 Agent。

## 恢复与冒烟命令

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source install/setup.bash

git status -sb
colcon test-result --verbose

# 无网络回归
ros2 run robot_llm_gateway plan_robot_task \
  --provider fake \
  --task '检查机器人健康状态' \
  --request-id fake_resume_001

# 真实 MiMo 密钥只在本机当前终端设置，不写入仓库
read -rsp 'MIMO_API_KEY: ' MIMO_API_KEY && export MIMO_API_KEY && echo

# 项目一仿真正常后执行真实两步只读 Agent Loop；不会移动机器人
ros2 run robot_agent_orchestrator run_read_only_agent \
  --task '检查机器人健康状态，然后只预览去 x=4.5 m、y=0.0 m、朝向0度的安全路径，不要移动机器人' \
  --goal-x 4.5 --goal-y 0.0 --goal-yaw-deg 0.0 \
  --use-sim-time \
  --run-id agent_route_live_001 \
  --trace-id trace_route_live_001 \
  --output ~/.ros/robot_agent/agent_route_live_001.json

# 完全离线的 deterministic RAG 构建与查询；learned A/B 见 versioned_rag.md
ros2 run robot_rag rag_build
ros2 run robot_rag rag_query \
  'semantic_keepout safety_ok 为 false 是否一定已经进入水坑？' \
  --distribution project1-v1 --top-k 3
ros2 run robot_rag rag_evaluate \
  --manifest ~/robot_agent_ws/rag/corpora/robotics_core_v1/evals/retrieval_dev_v2.json \
  --output-dir ~/.ros/robot_agent/rag/robotics_core_v2/baseline_development

# MCP 使用专用环境和 stdio；完整 baseline/BGE 参数见 docs/diagnosis_mcp.md
PYTHONPATH=src/robot_diagnosis_mcp:src/robot_rag:src/safe_agent_core \
  ~/robot_agent_mcp_env/bin/python -m robot_diagnosis_mcp.server_cli --help
```

该现场命令已经通过；重复运行必须更换 `run-id` 与 `trace-id`。输出不应出现 API key，且路径预览
只能调用 `/compute_path_to_pose`，不得调用导航 Action。
