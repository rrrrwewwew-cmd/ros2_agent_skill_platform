# Xiaomi MiMo Plan-only LLM Gateway

## 1. 本阶段交付什么

`robot_llm_gateway` 是项目二第一个真实 LLM 接入边界。生产后端只支持 Xiaomi MiMo；
`FakeProvider` 只用于无网络 CI，不是第二个线上 API，也不参与模型投票或故障切换。

当前版本只完成自然语言到结构化只读计划：

```text
用户任务
  → Prompt Registry（精确版本 + SHA-256）
  → MiMo Chat Completions
  → JSON 解析
  → Agent Plan Schema
  → Skill version/hash + 逐 Skill 输入 Schema 本地复核
  → plan-only result
```

它不会调用 Skill Runtime，不会创建 execution approval，不会发布 ROS topic，也不会让机器人移动。
下一阶段才会把通过验证的只读计划交给有界 Agent Loop。

## 2. 为什么仍然有 Provider 接口

Provider 接口不是为了同时接两个模型，而是隔离三类变化：

- MiMo HTTP、认证和错误格式；
- Agent 内部统一请求、结果和 Trace；
- 单元测试中的确定性离线响应。

仓库唯一真实实现是 `MimoProvider`。测试实现 `FakeProvider` 不访问网络，保证 CI 不需要 API
密钥、不产生费用且结果可复现。

MiMo 使用官方兼容 Chat Completions 地址
`https://api.xiaomimimo.com/v1/chat/completions`。请求为非流式，关闭 thinking，使用
`max_completion_tokens` 和 JSON object 输出模式。默认模型是 `mimo-v2.5-pro`，可以用
`MIMO_MODEL` 覆盖；获得平台明确批准的自定义部署地址时，可用 `MIMO_BASE_URL` 覆盖。
Token Plan 的 `tp-` 凭据只面向官方允许的编程工具场景，不能用于本自定义 Agent 后端；Gateway
会在网络请求前拒绝该类凭据。

## 3. 四层契约

1. `llm_plan_request.schema.json`：限制任务长度、模型、Prompt pin、token 和超时；
2. `prompt_definition.schema.json`：Prompt 版本、模式和允许 Skill 目录；
3. `agent_plan.schema.json`：只允许 `plan / clarify / refuse`，最多 6 步；
4. `llm_gateway_result.schema.json`：统一成功/失败、延迟、token usage 和错误码。

JSON 合法仍然不够。Gateway 会把每一步的 Skill `name + version + artifact_hash` 与 Prompt 中冻结
的 ACTIVE 目录逐项比较，并使用该 Skill 的嵌入式 `input_schema` 校验字段名、类型、范围、枚举、
必填项和额外字段。模型伪造 hash、把坐标字段传给语义查询，或生成不连续的 step id，都会得到
`plan_schema_invalid`，不会进入 Runtime。

## 4. Prompt Registry

首次真实基线 Prompt：

- id：`robot_task_planner`
- version：`0.1.0`
- canonical SHA-256：
  `7699bac29b1d5e7a08fdb8d666f7dff39ec758f3c203eb6e2d8f7e734b8179f2`
- 模式：`plan_only`
- 允许能力：三个只读 ACTIVE Skill
- 明确禁止：运动、写状态、Shell、任意 ROS、绕过审批和虚构执行结果

用户文本和 context 被序列化为独立 user JSON，并在系统 Prompt 中明确标记为不可信数据。冻结的
6 个 eval case 覆盖正常健康检查、语义查询、路径预览、运动越权、Prompt Injection 和缺少输入。

真实 v0.1.0 评测暴露出“通用 Plan Schema 通过，但具体 Skill 输入错误”的问题，因此当前默认版本
升级为：

- version：`0.2.0`
- canonical SHA-256：
  `652ad2e5b64735aefaea747a02634fc68796db0354501eb523f579bd940107ff`
- 新增：每个只读 Skill 的精确输入 JSON Schema；最小必要步骤规则；坐标路径预览不得借用只接受
  `map_profile + target_id` 的语义目标查询

v0.1.0 文件和评测结果仍保持不变，作为可审计的改进前基线。

## 5. 密钥与运行

密钥只从环境变量读取，不能写进参数文件、Prompt、Trace、Git 或命令历史：

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash

read -rsp 'MIMO_API_KEY: ' MIMO_API_KEY && export MIMO_API_KEY && echo
export MIMO_MODEL='mimo-v2.5-pro'

ros2 run robot_llm_gateway plan_robot_task \
  --task '检查机器人健康状态，并告诉我是否可以继续规划' \
  --request-id mimo_smoke_001
```

如果平台为自定义应用明确提供了专属 OpenAI-compatible 地址，再设置：

```bash
export MIMO_BASE_URL='控制台给出的、以 /v1 结尾的地址'
```

不要在这里填写 Token Plan 地址或 `tp-` Key。机器人 Agent 使用按量 API 的 `sk-` Key。

离线冒烟不需要密钥：

```bash
ros2 run robot_llm_gateway plan_robot_task \
  --provider fake \
  --task '检查机器人健康状态'
```

## 6. 失败策略

以下情况全部 fail closed，且不会执行任何工具：

- Prompt 文件不存在、Schema 失败或 hash 不匹配；
- MiMo 配置缺失、HTTP/超时、非 JSON 或空输出；
- 输出字段、步骤数或 decision 不符合 Schema；
- Skill 不在 allowlist，或版本/hash 与冻结目录不一致；
- Skill 输入缺字段、字段名/类型/范围错误或含额外字段；
- step id 重复、跳号或不从 1 开始；
- 请求声明的 Provider 与实际 Provider 不一致。

首版不做自动重试，避免一次 Agent 计划产生不可见的重复计费和不确定响应。后续如果增加重试，
也只允许在无副作用的规划阶段按固定次数执行，并写入 Trace。

## 7. 首次真实 API 证据

2026-07-19，`mimo-v2.5-pro` 首次真实 plan-only 调用成功：

- request id：`mimo_smoke_003`
- decision：`plan`
- Skill：`check_robot_health@0.2.0`
- artifact hash：与 ACTIVE artifact 完全一致
- 延迟：6522.272 ms
- token：输入 964、输出 249、总计 1213
- 本地结果：Gateway Schema、Agent Plan Schema 和 Prompt/catalog pin 全部通过

脱敏机器证据：`evidence/llm_gateway/mimo_plan_only_smoke_v1.json`。该结果只是尚未执行的计划，
不能被表述为“机器人已经健康”。

## 8. 冻结 Prompt 评测

`evaluate_robot_planner` 顺序运行 6 个冻结用例：三个只读能力选择、受控运动拒绝、Prompt
Injection 拒绝和歧义澄清。评分完全由本地代码完成，模型不能给自己打分。

```bash
ros2 run robot_llm_gateway evaluate_robot_planner \
  --output-dir ~/.ros/robot_agent/mimo_planner_evaluation_v1 \
  --evaluation-id mimo_planner_eval_v1
```

该命令最多产生 6 次 MiMo 付费调用。默认串行执行且首次 Provider 错误立即停止；每个成功 case
保存在 `cases/<case_id>/result.json`，再次运行会复核配置并断点续跑。输出：

- `sample_results.csv`：逐样本 decision、实际 Skill、缺失/越权 Skill、延迟和 token；
- `summary.json`：Schema 成功率、decision 准确率、Skill policy 准确率、Injection 拒绝率与成本；
- 原始 Gateway result：保留 Prompt/request hash 和 provider request id，不包含 API key。

可先运行单个用例控制费用：

```bash
ros2 run robot_llm_gateway evaluate_robot_planner \
  --output-dir ~/.ros/robot_agent/mimo_planner_evaluation_v1 \
  --evaluation-id mimo_planner_eval_v1 \
  --case-id prompt_injection_shell
```

安装态 Fake Provider 已获得 6/6 PASS，用于证明评测机制而非模型质量。修复前完整工作区为 139 项测试
通过。

## 9. 首次完整真实评测与修复

`robot_task_planner@0.1.0` 的真实 MiMo 基线为 5/6 PASS：Schema 成功率、decision 准确率、
Prompt Injection 拒绝率均为 100%，Skill policy 准确率为 83.33%；平均延迟 9176 ms，总计
7159 tokens。唯一失败的路径预览计划额外加入了 `query_semantic_target`，并为其生成了错误的坐标
字段。这项失败被保留，没有通过放宽 allowed Skill 来“做绿”。

详细分析见 `docs/mimo_prompt_evaluation_v1.md`，脱敏机器证据见
`evidence/llm_gateway/mimo_prompt_evaluation_v1.json`。v0.2.0 修复后的安装态 Fake 评测为 6/6，
全工作区为 143 项测试、0 error、0 failure、0 skipped。下一项真实验证只定向运行
`route_preview_read_only`，避免重复支付其余五个已经证明的问题类型。
