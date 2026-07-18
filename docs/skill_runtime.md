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
  → verify Ed25519 release envelope with trusted public key
  → validate inputs and exact ROS permissions
  → fixed approved adapter
  → bounded subprocess timeout
  → result Schema and semantic postconditions
  → AgentRun state + append-only JSONL Trace
```

## 2. 五层拒绝

1. **治理状态**：`DRAFT` 到 `SIGNED` 都不能执行，只有 `ACTIVE` 可以进入适配器；
2. **代码身份**：invocation、Registry、artifact lock 和本地文件计算值四者 hash 必须一致；
3. **发布身份**：Ed25519 envelope 必须通过部署时固定的受信公钥再次验证；
4. **参数权限**：输入通过 Skill manifest JSON Schema，ROS 权限必须与代码内批准适配器完全一致；
5. **输出验证**：返回值既要通过 JSON Schema，也要满足语义不变量，例如 `healthy` 才能
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

参考 Skill `check_robot_health@0.2.0` 已通过仿真、审批、Ed25519 签名和验签并进入 `ACTIVE`。
每个 invocation 的 `run_id` 与 `trace_id` 必须唯一：

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 run robot_skill_runtime skill_execute \
  --invocation examples/check_robot_health_invocation_v1.json \
  --trusted-public-key ~/.ros/robot_agent/keys/release_ed25519.pub.pem \
  --use-sim-time
```

只有同一 hash 的 `ACTIVE` 版本且签名验证通过，才可启动固定的 `HealthSkillAdapter`。适配器使用参数
数组启动 Python 模块，明确设置 `shell=False`，并使用 manifest 的 10 秒上限终止超时进程。ROS 图
不可用时，调用本身可以是 `SUCCEEDED`，但健康输出必须是 `unsafe`；发布门、工具状态和机器人安全
结论因此保持为三个不同层次。

## 6. 当前边界

- 仅实现 `check_robot_health` approved adapter；
- Registry 签名由独立 verifier 验证，Runtime 只持有受信公钥、不持有私钥；
- 当前没有 LLM、Prompt 或 MCP；
- Trace 包含结构化输入输出，但后续接入模型前仍需增加字段级脱敏策略。
