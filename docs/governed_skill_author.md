# 受治理 ROS 2 Skill Author

## 核心结论

`robot_skill_author@0.1.0` 不是“让模型输出 Python 后立即运行”。MiMo 只输出一个受
`skill_author_plan.schema.json` 约束的工作流草案；源代码由代码仓库内的确定性 renderer 从批准模板
生成。候选最多自动修复两轮，通过所有机器门后仍只到 `SIMULATION_TESTED`，必须由人检查 diff、
按 artifact hash 批准、签名并完成 adapter review，才可能进入 `ACTIVE`。

## 流水线

```text
Skill requirement
  → deterministic request policy
  → versioned RAG + hash-bound citations
  → MiMo structured workflow draft
  → schema + dependency/order policy
  → deterministic ROS 2 package renderer
  → static AST/file/permission scan
  → no-shell compile + colcon build
  → generated unit tests
  → bounded simulation fixtures
  → Registry: SIMULATION_TESTED
  → HUMAN APPROVAL REQUIRED
```

模型不能提供源码、import、ROS 名称、文件路径或 shell 命令。允许依赖只有四个已发布原子 Skill；
受控工作流必须包含 `preview_safe_route → navigate_to_approved_pose`，批准导航必须是最后一步。
健康检查必须先于路径预览。

## 安全机制

1. 请求层确定性拒绝 `/cmd_vel`、任意 shell、`os.system` 和批准绕过描述；
2. JSON Schema 限制名字、版本、安全等级、依赖、测试数量和字段集合；
3. renderer 只产生固定 ament Python 包结构，模型文本永不拼接进源代码；
4. 静态扫描拒绝 symlink、路径逃逸、动态 import、网络和超限文件；
5. sandbox 使用参数数组调用固定命令，不使用 shell，并删除 API key 与代理环境；
6. Registry 状态迁移不能跳级，流水线不产生签名，也不自动激活；
7. 人工批准命令同时绑定候选 name、version 和 SHA-256，批准后仍需独立签名与 adapter review。

## 10 需求评测

`evaluate_skill_author` 运行冻结的 10 个需求：6 个合法 read-only/controlled 组合会真实执行
`compileall`、`colcon build`、pytest unit 和 simulation fixtures，并验证 Registry 只到
`SIMULATION_TESTED`；4 个 `/cmd_vel`、任意 shell、批准绕过和未知依赖需求必须被确定性拒绝。

报告包含首次构建率、单元测试率、仿真率、违规拒绝率、平均修复次数和自动激活数。发布硬门是
`automatic_activation_count == 0`，而不是“生成成功率越高越好”。

## Skill 与 Codex Skill 的区别

这里的 Skill 是项目二定义的机器人能力契约：包含 ROS 权限、输入 Schema、效果、安全等级、
artifact 和 Registry 生命周期。它不是一段给聊天模型看的提示词文件。`SKILL.md` 是人类/Agent
可读说明，真正的安全边界来自 Schema、固定 adapter、Registry、签名、审批和运行时后置条件。
