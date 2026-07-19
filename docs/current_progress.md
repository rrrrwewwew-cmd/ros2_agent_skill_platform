# 项目二当前进度检查点

更新时间：2026-07-19

本文件是休息、重启或上下文切换后的唯一恢复入口。恢复时先读本文件，再查看 Git 历史；不要
重新搭建项目一、重新实现前四个 Skill，也不要恢复已经取消的“双 Provider”设计。

## 当前结论

项目二已完成确定性安全底座、真实 MiMo 接入和首轮 Prompt 质量评测。生产 LLM 只使用 Xiaomi
MiMo；`FakeProvider` 仅服务无网络 CI，不是第二个 API。当前 LLM Gateway 只生成只读计划，不执行
Skill，不触发审批，也不控制机器人。首轮真实评测发现的逐 Skill 输入合约缺口已经在 Prompt
v0.2.0 和 Gateway 本地校验中修复，等待一次付费定向回归后进入只读 Agent Loop。

- 工作区：`/home/li/robot_agent_ws`
- Git 分支：`feature/skill-registry-state-machine`
- 前四个 Skill：均已签名并处于 `ACTIVE`
- ROS 2 包：7 个
- 当前测试基线：143 项，0 error、0 failure、0 skipped
- LLM 真实后端：Xiaomi MiMo Chat Completions
- 当前默认 Prompt：`robot_task_planner@0.2.0`
- Prompt canonical SHA-256：
  `652ad2e5b64735aefaea747a02634fc68796db0354501eb523f579bd940107ff`
- 安装态 Fake Provider 冒烟：通过
- MiMo 真实 API 冒烟：通过；`mimo_smoke_003`，计划选择 `check_robot_health@0.2.0`
- MiMo v0.1.0 真实 6-case 基线：5 PASS / 1 FAIL / 0 error；失败已定位并保留
- v0.2.0 安装态 Fake 回归：6/6 PASS；逐 Skill 输入合约门控已通过单元测试
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
PASS。完整工作区当前为 143 项测试通过。

新增机器契约：

- `schemas/llm_plan_request.schema.json`
- `schemas/prompt_definition.schema.json`
- `schemas/agent_plan.schema.json`
- `schemas/llm_gateway_result.schema.json`

详细设计见 `docs/llm_gateway.md`。

## 架构决策修正

早期检查点要求先手写 `observe_and_avoid_water_risk` 和 `return_home_safely`，再接 LLM。经过架构
复盘后该顺序已废止：前四个 Skill 已经覆盖状态查询、知识查询、路径规划和受控动作四种最重要的
Tool Calling 形态，足以安全启动 Agent 层。第五、第六 Skill 将在后续 RAG + Skill Author 阶段
作为“模型辅助生成、构建、仿真、审批、签名、激活”的完整案例，而不是继续人工堆确定性工具。

这项修正不会降低安全性。模型当前只能规划三个只读 Skill；受控导航仍必须由已有 Runtime、一次性
approval、动态前置条件和后置条件处理。

## 下次唯一主线

1. 使用 v0.2.0 只定向复测 `route_preview_read_only`，验证最小 Skill 选择和四项路径输入；
2. 定向回归通过后，实现有界只读 Agent Loop：计划 → 输入校验 → Runtime 调用 → 证据 → Trace；
3. 只读闭环通过后，再决定何时向模型暴露受控导航；运动仍需人工审批；
4. 随后进入版本化 RAG、MCP 实验诊断工具、RAG-assisted Skill Author 和最终部署。

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

# v0.2.0 定向真实回归；只产生一次 MiMo 调用
ros2 run robot_llm_gateway evaluate_robot_planner \
  --output-dir ~/.ros/robot_agent/mimo_planner_evaluation_v2_route \
  --evaluation-id mimo_planner_eval_v2_route \
  --case-id route_preview_read_only
```

真实冒烟预期只输出结构化计划和运行元数据，不应出现 API key，也不会执行健康检查或控制机器人。
