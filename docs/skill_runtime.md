# Registry-gated Skill Runtime

## 1. 作用

`robot_skill_runtime` 是 LLM/Agent 与 ROS Skill 之间的确定性执行闸门。模型以后只能产生结构化
invocation；不能直接 import Python、运行 Shell、发布 ROS 话题或调用未登记接口。

```text
typed invocation
  → exact Registry lookup
  → require ACTIVE
  → invocation hash == Registry hash
  → recompute artifact lock
  → validate inputs and exact ROS permissions
  → fixed approved adapter
  → bounded subprocess timeout
  → result Schema and semantic postconditions
  → AgentRun state + append-only JSONL Trace
```

## 2. 四层拒绝

1. **治理状态**：`DRAFT` 到 `SIGNED` 都不能执行，只有 `ACTIVE` 可以进入适配器；
2. **代码身份**：invocation、Registry、artifact lock 和本地文件计算值四者 hash 必须一致；
3. **参数权限**：输入通过 Skill manifest JSON Schema，ROS 权限必须与代码内批准适配器完全一致；
4. **输出验证**：返回值既要通过 JSON Schema，也要满足语义不变量，例如 `healthy` 才能
   `safe_to_proceed=true`。

运行时不会自行批准、签名或激活 Skill，因此不能把执行接口反向用作治理绕过。

## 3. “Skill 成功”与“机器人安全”不同

健康检查正常完成并返回 `unsafe` 时：

- AgentRun 是 `SUCCEEDED`，说明工具调用和证据契约都成功；
- `output.safe_to_proceed=false`，后续运动 Skill 必须停止；
- 只有进程超时、输出损坏、权限失败等才使 AgentRun 进入 `FAILED`。

该区分避免把真实的危险检测误报成软件故障，也避免上层因“工具失败重试”反复执行检查或动作。

## 4. Artifact lock

`artifacts/<name>/<version>.json` 列出构成发布物的文件。`sha256-file-list-v1` 对每个文件计算
SHA-256，再对包含相对路径的有序摘要清单计算最终 SHA-256。绝对路径、`..`、重复文件、缺失文件
和 symlink 都被拒绝。

## 5. CLI

下面的参考 Skill 当前只到 `SIMULATION_TESTED`，所以命令应被拒绝且不会调用 ROS 适配器：

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 run robot_skill_runtime skill_execute \
  --invocation examples/check_robot_health_invocation_v1.json \
  --use-sim-time
```

拒绝本身会保存 AgentRun `FAILED` 状态和 JSONL Trace。完成外部签名验证并将同一 hash 的版本推进为
`ACTIVE` 后，同一调用才可启动固定的 `HealthSkillAdapter`。适配器使用参数数组启动 Python 模块，
明确设置 `shell=False`，并使用 manifest 的 10 秒上限终止超时进程。

## 6. 当前边界

- 仅实现 `check_robot_health` approved adapter；
- Registry 签名仍由外部 verifier 提供，Runtime 不持有私钥；
- 当前没有 LLM、Prompt 或 MCP；
- Trace 包含结构化输入输出，但后续接入模型前仍需增加字段级脱敏策略。
