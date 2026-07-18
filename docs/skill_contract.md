# Skill 契约说明

## 1. Skill 包

一个可注册 Skill 至少包含：

```text
<skill-name>/
├── SKILL.md
├── skill.yaml
├── skill-card.md
└── evals/
    └── evals.json
```

执行型 Skill 后续还必须包含 ROS 实现、launch/config 和测试。文档 Skill 可以没有 ROS
entrypoint，但必须明确 `read_only` 且无写权限。

## 2. 文件职责

- `SKILL.md`：供 Agent 使用的领域说明、步骤、失败处理和禁令；
- `skill.yaml`：机器可读输入、前置条件、效果、权限和运行时限制；
- `skill-card.md`：来源、作者、适用范围、风险、测试和治理状态；
- `evals/evals.json`：代表性正例、拒绝例和边界场景。

自然语言指令不能扩大 `skill.yaml` 的权限。两者冲突时以机器契约和全局安全策略为准。

## 3. 命名与版本

- 名称使用小写 snake_case；
- 版本使用 SemVer；
- 每次实现、权限、前置条件或行为变更必须升级版本；
- 已签名 artifact 不允许就地覆盖。

## 4. 安全等级

| 等级 | 含义 | 审批 |
| --- | --- | --- |
| `read_only` | 不改变机器人或地图状态 | 可自动 |
| `controlled` | 可启动受控任务 | 执行前动态检查 |
| `high` | 修改安全策略或高影响状态 | 必须人工批准 |
| `emergency` | 取消和停止 | 始终允许 |

`high` Skill 的 `requires_human_approval` 必须为 true。

## 5. 权限

Manifest 分别声明：

- `topics_read`；
- `topics_write`；
- `services`；
- `actions`。

首版全局拒绝任何 Skill 声明写入 `/cmd_vel` 或等价直接底盘速度接口。导航必须通过批准的 Nav2
Action wrapper。未来即使增加低层控制，也必须使用独立实时安全控制器，不能仅靠 Agent 权限。

## 6. 前置条件与效果

前置条件是执行前可验证的布尔事实，例如：

- `nav2_active`；
- `tf_fresh`；
- `safety_monitor_ok`；
- `goal_inside_map`；
- `skill_artifact_verified`。

效果只描述允许发生的状态变化，例如 `may_move_robot`、`may_update_semantic_map`。Executor 不能
从自然语言描述推断未声明效果。

## 7. 超时、取消和幂等性

每个执行型 Skill 必须声明有限超时。会移动机器人或等待外部资源的 Skill 必须声明取消行为。
Registry 还会记录是否幂等；非幂等 Skill 的自动重试默认禁用。

## 8. 当前机器可读规范

完整字段见 [`schemas/skill.schema.json`](../schemas/skill.schema.json)。Phase 0 验证器实现关键安全
检查；后续 Registry 将使用完整 JSON Schema 验证和 artifact hash。
