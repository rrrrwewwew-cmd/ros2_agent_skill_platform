# ROS 2 Agent Skill Platform

> RAG-assisted ROS 2 skill authoring, governed registration, safe agent
> execution, experiment diagnosis, and reproducible evaluation.

项目二研究如何让 LLM 在机器人系统中安全地获得、选择、组合和执行能力。用户可以用自然语言
描述任务或新 Skill；系统通过版本化 RAG 检索 ROS 2 文档、已有接口、模板和安全规则。生成的
ROS 2 Skill 只有通过 schema、静态检查、构建、测试、仿真和人工批准后，才能进入 Skill
Registry。运行时 Agent 只能调用已批准 Skill，不能直接发布速度或执行任意代码。

## 与项目一的关系

- 项目一 `wsl_ros2`：Grounded-VLM 风险感知、RGB-D 地图投影、语义地图、Nav2 动态 Keepout；
- 项目二 `ros2_agent_skill_platform`：RAG、Skill 编写与注册、安全 Agent、故障注入和评测。

两个项目是独立 Git 仓库。项目二通过 ROS 2 接口复用项目一，不复制项目一源码：

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source ~/robot_agent_ws/install/setup.bash
```

## 四个闭环

1. **Skill 编写闭环**：需求 → RAG → 代码/契约/测试生成 → 构建与仿真 → 审批 → Registry；
2. **安全执行闭环**：任务 → 检索 → 结构化计划 → 双重策略校验 → Skill 执行 → 结果验证；
3. **实验诊断闭环**：查询日志 → Python 分析 → 异常时间段 → 控制关联 → 原因假设 → 图表报告；
4. **评测闭环**：正常/模糊/恶意/故障场景 → Trace → 安全和任务指标 → 可复算报告。

## 当前状态

确定性安全底座、真实 MiMo 规划评测和只读 Agent Loop 已完成。仓库已包含：

- [最新进度检查点与下次恢复入口](docs/current_progress.md)；
- [系统架构](docs/architecture.md)；
- [分阶段计划与验收标准](docs/project_plan.md)；
- [Skill 契约说明](docs/skill_contract.md)；
- [实验日志诊断 Agent 契约](docs/experiment_diagnosis.md)；
- [Skill Registry 与持久化状态机](docs/registry_state_machine.md)；
- [只读机器人健康 Skill 实现](docs/robot_health_skill.md)；
- [Registry-gated Skill Runtime](docs/skill_runtime.md)；
- [Ed25519 Skill 发布签名与运行时验签](docs/release_signing.md)；
- [`query_semantic_target` 只读语义地图 Skill](docs/semantic_query_skill.md)；
- [`preview_safe_route` 只读安全路径预览 Skill](docs/route_preview_skill.md)；
- [`navigate_to_approved_pose` 一次性批准导航 Skill](docs/approved_navigation_skill.md)；
- [Xiaomi MiMo plan-only LLM Gateway 与 Prompt Registry](docs/llm_gateway.md)；
- [持久化只读 Agent Loop、证据门控与父子 Trace](docs/read_only_agent_loop.md)；
- [机器可读 Skill JSON Schema](schemas/skill.schema.json)；
- [第一个只读 Skill：`check_robot_health`](skills/check_robot_health)；
- [第二个只读 Skill：`query_semantic_target`](skills/query_semantic_target)；
- [第三个只读 Skill：`preview_safe_route`](skills/preview_safe_route)；
- [第四个受控 Skill：`navigate_to_approved_pose`](skills/navigate_to_approved_pose)；
- `safe_agent_core` ROS 2 Python 包和最小契约验证器；
- `robot_skill_registry` SQLite Registry、审批/签名状态与 Agent run store；
- ROS 2 Jazzy CI。

Phase 1 已提供实验清单、Agent Trace、时间序列关联、距离矩阵、异常窗口、可复算报告、不可变
Skill Registry、持久化 Agent run、三个已激活的只读 Skill（机器人健康、语义地图查询和 Nav2
安全路径预览）、一个已激活的一次性批准导航 Skill，以及只允许通过
hash 和 Ed25519 发布证明的 `ACTIVE` artifact 进入固定适配器的 Skill Runtime。它先使用确定性 Python 与事务
状态建立证据和治理边界。MiMo plan-only LLM Gateway、Prompt Registry、可断点续跑评测器和
有界只读 Agent Loop 已完成。真实 Prompt 基线与修复回归均已冻结；下一项是仿真现场运行
`MiMo → health → route preview → evidence gate → Trace`，之后进入 RAG 和 MCP 阶段。

## 仓库结构

```text
robot_agent_ws/
├── src/safe_agent_core/       # Skill 契约、策略和状态机底座
├── src/robot_skill_registry/  # 不可变版本、治理事件和 Agent run 状态
├── src/robot_skill_runtime/   # ACTIVE/hash/权限门控与批准适配器
├── src/robot_semantic_skills/ # 项目一持久化语义地图的受控只读工具
├── src/robot_navigation_skills/ # 只读 Nav2 规划与语义 Keepout 路径验证
├── src/robot_controlled_navigation_skills/ # 一次性批准的固定 Nav2 动作适配器
├── src/robot_llm_gateway/     # MiMo plan-only Gateway、Prompt Registry 与 Schema 门控
├── src/robot_agent_orchestrator/ # 持久化只读 Agent Loop、证据门控与父子 Trace
├── artifacts/                 # 版本化 Skill artifact file locks
├── skills/                    # 版本化、可评测的机器人/Agent Skill
├── schemas/                   # 机器可读契约
├── examples/                  # 冻结实验样例和可复算输入
├── docs/                      # 架构、计划和安全边界
└── .github/workflows/         # ROS 2 Jazzy CI
```

后续包将按验收阶段加入，而不是一次性建立空框架：

- `robot_rag`；
- `robot_mcp_tools`；
- `robot_skill_author`；
- `safe_agent_eval`。

## 目标技术栈

最终闭环明确覆盖 LLM API、版本化 Prompt、结构化 Tool Calling、有界 Agent Loop、持久化状态、
Python 数据分析、版本化 RAG、MCP、Trace/Replay/可观测性、人工审批和可复现部署。MCP 只暴露
声明过权限的分析工具或已批准 Skill，不作为任意 Shell 或任意 ROS graph 后门。

## 本地构建

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
colcon test
colcon test-result --verbose
```

验证示例 Skill：

```bash
ros2 run safe_agent_core skill_validate \
  ~/robot_agent_ws/skills/check_robot_health/skill.yaml
```

运行只读健康检查：

```bash
ros2 run safe_agent_core check_robot_health --ros-args \
  -p use_sim_time:=true \
  -p required_sensors:="[/scan, /camera/image]"
```

运行已经审批、签名并激活的参考 Skill（`run_id` 与 `trace_id` 每次必须唯一）：

```bash
ros2 run robot_skill_runtime skill_execute \
  --invocation ~/robot_agent_ws/examples/check_robot_health_invocation_v1.json \
  --trusted-public-key ~/.ros/robot_agent/keys/release_ed25519.pub.pem \
  --use-sim-time
```

Runtime 会重新计算 artifact hash、验证 Ed25519 发布 envelope、输入和权限，再调用固定 adapter。
完整机器人栈在线时返回 `healthy`；ROS 图不可用时工具调用仍可正常完成，但输出为
`safe_to_proceed=false`，下游运动必须停止。

运行真实 MiMo 两步只读 Agent Loop（要求项目一仿真正常、当前终端已设置 `MIMO_API_KEY`）：

```bash
source ~/ros2_ws/install/setup.bash

ros2 run robot_agent_orchestrator run_read_only_agent \
  --task '检查机器人健康状态，然后只预览去 x=4.5 m、y=0.0 m、朝向0度的安全路径，不要移动机器人' \
  --goal-x 4.5 --goal-y 0.0 --goal-yaw-deg 0.0 \
  --use-sim-time \
  --run-id agent_route_live_001 \
  --trace-id trace_route_live_001
```

循环只执行 Prompt catalog 中的只读 Skill。每个步骤仍会重新验证 ACTIVE Registry、artifact、
Ed25519、权限、输入和结果；健康证据不安全时不会调用路径预览。

运行冻结的抖动实验证据分析：

```bash
ros2 run safe_agent_core experiment_analyze \
  --manifest ~/robot_agent_ws/examples/experiment_jitter_v1/manifest.json \
  --output-dir /tmp/robot_agent_jitter_report
```

该命令不调用 LLM；它验证输入 hash，计算轨迹距离矩阵，对齐控制指令，标出异常窗口，并输出
`analysis.json`、`report.md`、`trajectory.svg` 和 `motion_timeseries.svg`。

初始化 Registry 并登记参考 Skill：

```bash
ros2 run robot_skill_registry skill_registry \
  --db ~/.ros/robot_agent/registry.db init

ros2 run robot_skill_registry skill_registry \
  --db ~/.ros/robot_agent/registry.db register \
  --manifest ~/robot_agent_ws/skills/check_robot_health/skill.yaml
```

Registry 使用 SQLite 事务、不可变 `name + version`、artifact hash、专用审批/Ed25519 验签操作和追加式
审计事件。Agent run 同样持久化；重启后遗留活动 run 默认转为 `ABORTED`，不会自动重放可能已经
执行过的机器人动作。

## 冻结边界

项目二不会让 LLM 在线生成任意代码后直接控制机器人。不会提供任意 Shell、任意 ROS 图接口、
直接 `/cmd_vel`、多 Agent、VLA 控制或 Web 搜索。生成 Skill 只能在隔离构建/仿真环境运行，
通过审批后才能注册。最终部署指锁定依赖、容器/ROS 2 launch、配置、CI 和版本化 Release；真机
安全认证与生产现场上线不在作品集 v1 的完成范围内。
