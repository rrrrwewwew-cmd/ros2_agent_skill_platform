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
  → Skill version/hash 本地复核
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
的 ACTIVE 目录逐项比较。模型伪造一个格式正确的 hash 仍会得到 `plan_schema_invalid`。

## 4. Prompt Registry

首个 Prompt：

- id：`robot_task_planner`
- version：`0.1.0`
- canonical SHA-256：
  `7699bac29b1d5e7a08fdb8d666f7dff39ec758f3c203eb6e2d8f7e734b8179f2`
- 模式：`plan_only`
- 允许能力：三个只读 ACTIVE Skill
- 明确禁止：运动、写状态、Shell、任意 ROS、绕过审批和虚构执行结果

用户文本和 context 被序列化为独立 user JSON，并在系统 Prompt 中明确标记为不可信数据。冻结的
6 个 eval case 覆盖正常健康检查、语义查询、路径预览、运动越权、Prompt Injection 和缺少输入。

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

安装态 Fake Provider 已获得 6/6 PASS，用于证明评测机制而非模型质量。完整工作区当前 139 项测试
通过。
