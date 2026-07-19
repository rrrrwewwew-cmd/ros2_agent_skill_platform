# 只读 Agent Loop 设计与运行

## 1. 交付边界

`robot_agent_orchestrator@0.1.0` 把已经通过评测的 MiMo plan-only Gateway 与现有 governed Skill
Runtime 接成第一个真正的 Agent 闭环：

```text
自然语言任务
  → MiMo 生成 plan / clarify / refuse
  → Plan Schema + Prompt pin + 逐 Skill 输入 Schema
  → 父级持久状态机 VALIDATING
  → 顺序 Tool Calling
  → 每个 Tool 再经过 ACTIVE Registry、artifact、Ed25519、权限和后置条件校验
  → 确定性证据门控
  → 父级 VERIFYING / SUCCEEDED / ABORTED / FAILED
```

当前仍然只允许三个只读 Skill。Agent Loop 不接受 execution approval，不暴露
`navigate_to_approved_pose`，也不会发布运动命令。它不会再调用一次 LLM 来“判断工具是否成功”；工具
结果由本地 Schema、Runtime postcondition 和确定性策略解释，避免模型给自己打分。

## 2. 父子状态与 Trace

一次自然语言任务创建一个父 run，例如 `agent_live_001`。MiMo 计划中的每一步创建独立子 run：

- `agent_live_001.step1`
- `agent_live_001.step2`

父 run 记录完整生命周期、冻结计划、执行顺序和最终状态；子 run 保留每个 Skill 原有的 Registry、
签名、适配器和后置条件证据。两层 JSONL Trace 通过 child run id 关联，既能查看整次 Agent 决策，也
能下钻到一个 ROS Tool 的具体输入与结果。

父级正常路径为：

```text
IDLE → RETRIEVING → PLANNING → VALIDATING
     → EXECUTING → VERIFYING → SUCCEEDED
```

Provider、Schema、Registry 或 Runtime 错误进入 `FAILED`。澄清、拒绝和证据阻断进入 `ABORTED`，
不会伪装成执行成功。

## 3. 证据门控

Tool 返回 `status=succeeded` 只表示调用和结果契约有效，不代表环境安全。例如健康检查可以成功读取
到 `safe_to_proceed=false`。因此父循环还使用代码拥有的 evidence gate：

| Skill | 继续后续步骤的条件 |
| --- | --- |
| `check_robot_health` | `safe_to_proceed == true` |
| `query_semantic_target` | `found == true` |
| `preview_safe_route` | `safe_to_execute == true` |

中间步骤不通过 gate 时，后续 Tool 不会调用，父结果为 `blocked_by_evidence`。如果最后一步本身是
一次只读查询，则 Agent 可以正确完成查询，同时返回 `safe_to_continue=false`；例如路径预览成功但
结论是不安全，这不是 Runtime 故障。

## 4. 并发与崩溃恢复

Agent Loop 使用非阻塞进程文件锁保证单机器人同一时间只有一个父循环。第二个并发进程会在调用
MiMo 或 Tool 前被拒绝。获得锁后，启动逻辑会把数据库中旧的非终态 run 标记为
`ABORTED/process_restart_fail_closed`，不会在重启后自动重复工具调用。

这两个机制必须结合：只有文件锁证明不存在仍活着的 Agent 进程后，才能把非终态记录视为崩溃
残留；否则所谓“恢复”可能误伤正在运行的任务。

## 5. 测试覆盖

当前 13 项 Orchestrator 测试覆盖：

- 两步顺序执行和父级 Trace；
- 不安全健康证据阻断第二步；
- 最终路径预览为 unsafe 时如实返回；
- 子 Runtime 失败后的 fail-fast；
- clarify/refuse 零 Tool 调用；
- Provider 失败持久化；
- 未知/非只读 Skill 二次权限拦截；
- 子结果 Skill 身份错配；
- 崩溃残留恢复；
- 并发 Agent 文件锁；
- Fake LLM 计划真实穿过 ACTIVE Registry、Ed25519、artifact 和 Runtime adapter。

最后一项不是 Mock Executor，因此证明父子数据库、签名校验和 Runtime 的集成边界确实接通。

## 6. 仿真现场验证

先正常启动项目一的 rbot 仿真、Nav2、AMCL、语义 Keepout 和相机，再在保存有 MiMo Key 的终端执行：

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source install/setup.bash

ros2 run robot_agent_orchestrator run_read_only_agent \
  --task '检查机器人健康状态，然后只预览去 x=4.5 m、y=0.0 m、朝向0度的安全路径，不要移动机器人' \
  --goal-x 4.5 \
  --goal-y 0.0 \
  --goal-yaw-deg 0.0 \
  --use-sim-time \
  --run-id agent_route_live_001 \
  --trace-id trace_route_live_001 \
  --output ~/.ros/robot_agent/agent_route_live_001.json
```

预期 MiMo 只规划 `check_robot_health → preview_safe_route`。输出应有两个成功子步骤、父状态
`SUCCEEDED`、`planner_decision=plan`，并明确给出 `safe_to_continue`。该命令只读取健康、Nav2 路径
和 Keepout，不发送运动 action。
