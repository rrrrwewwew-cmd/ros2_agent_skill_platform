# ROS 2 Agent Skill Platform

> RAG-assisted ROS 2 skill authoring, governed registration, safe agent
> execution, and reproducible evaluation.

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

## 三个闭环

1. **Skill 编写闭环**：需求 → RAG → 代码/契约/测试生成 → 构建与仿真 → 审批 → Registry；
2. **安全执行闭环**：任务 → 检索 → 结构化计划 → 双重策略校验 → Skill 执行 → 结果验证；
3. **评测闭环**：正常/模糊/恶意/故障场景 → Trace → 安全和任务指标 → 可复算报告。

## 当前状态

当前为 Phase 0：冻结架构、范围、Skill 契约和评测指标。仓库已包含：

- [系统架构](docs/architecture.md)；
- [分阶段计划与验收标准](docs/project_plan.md)；
- [Skill 契约说明](docs/skill_contract.md)；
- [机器可读 Skill JSON Schema](schemas/skill.schema.json)；
- [第一个只读 Skill：`check_robot_health`](skills/check_robot_health)；
- `safe_agent_core` ROS 2 Python 包和最小契约验证器；
- ROS 2 Jazzy CI。

## 仓库结构

```text
robot_agent_ws/
├── src/safe_agent_core/       # Skill 契约、策略和状态机底座
├── skills/                    # 版本化、可评测的机器人/Agent Skill
├── schemas/                   # 机器可读契约
├── docs/                      # 架构、计划和安全边界
└── .github/workflows/         # ROS 2 Jazzy CI
```

后续包将按验收阶段加入，而不是一次性建立空框架：

- `robot_skill_registry`；
- `robot_skill_runtime`；
- `robot_rag`；
- `robot_skill_author`；
- `safe_agent_eval`。

## 本地构建

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
colcon test --packages-select safe_agent_core
colcon test-result --verbose
```

验证示例 Skill：

```bash
ros2 run safe_agent_core skill_validate \
  ~/robot_agent_ws/skills/check_robot_health/skill.yaml
```

## 冻结边界

项目二不会让 LLM 在线生成任意代码后直接控制机器人。不会提供任意 Shell、任意 ROS 图接口、
直接 `/cmd_vel`、多 Agent、VLA 控制或 Web 搜索。生成 Skill 只能在隔离构建/仿真环境运行，
通过审批后才能注册。
