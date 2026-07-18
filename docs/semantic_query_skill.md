# `query_semantic_target` 只读语义地图 Skill

## 1. 为什么不直接暴露项目一 CLI

项目一的 `semantic_map_query` 面向人工终端：支持自然语言别名、允许 `--store-file`，并在 JSON 前打印
可读标题。直接把它当 Agent Tool 会产生两个问题：调用者可以选择任意文件，输出也不是严格的单一
JSON 文档。

项目二因此消费项目一已经稳定的 `semantic_landmarks_v1.json` 数据契约，但建立自己的受控边界：

```text
Agent input: map_profile + canonical target_id
  → manifest JSON Schema allowlist
  → Runtime fixed SemanticTargetQueryAdapter
  → code-owned profile → file mapping
  → read exact bytes once + SHA-256
  → validate project-one schema-v1 evidence
  → normalized result Schema + semantic postconditions
```

两个仓库没有源码合并。项目一负责产生语义地图，项目二只读取其部署数据接口。

## 2. 固定 profile

| profile | 固定数据源 | 用途 |
| --- | --- | --- |
| `semantic_landmarks_v1` | `~/.ros/semantic_nav_eval/semantic_landmarks_v1.json` | green/blue/red 等基础地标 |
| `rbot_water_puddle_v2` | `~/.ros/semantic_nav_eval/rbot_water_puddle_landmarks_v2.json` | Grounded-VLM 水坑风险地标 |

`store_file` 只存在于内部 CLI，不属于 Skill manifest 输入。Runtime adapter 根据 profile 生成参数数组，
设置 `shell=False`，Agent 无法传路径、Shell 片段或额外 ROS 名称。

## 3. 输入和输出

输入只接受版本化 allowlist 中的 canonical id。中文或自由文本将在后续 RAG/Planner 层解析为 id，执行
边界不会猜测别名。

输出状态：

- `found`：记录存在且计数、坐标、标准差、时间戳和证据字段全部有效；
- `not_found`：数据源有效，但没有该 target；
- `unavailable`：批准的数据文件不存在或不能读取；
- `invalid`：文件或目标记录违反数据契约。

`found` 不等于允许运动。它只证明某份持久化地图包含有效记录；下游 Skill 仍需检查任务所需的证据
新鲜度、机器人健康、路径和 Keepout。查询结果保存源文件内容 SHA-256，使离线 Trace 能确认具体输入
版本。

## 4. 真实数据验证

安装后的 CLI 已对两个项目一数据源验证：

- `green_box`：2 次接受、0 次拒绝，均值 `(-1.968639, -0.694886, 0.562705)` m；
- `water_puddle`：1 次接受、0 次拒绝，位置 `(1.671050, 0.007173, 0.004796)` m。

单元和 Runtime 测试覆盖：源文件字节不变、缺失目标、缺失/损坏文件、计数不一致、非有限数值、
profile/path escape、输出身份不一致、timeout、artifact hash、Ed25519 签名和 ACTIVE 执行门。
