# MiMo Planner v0.1.0 真实评测结论

2026-07-19 使用 `mimo-v2.5-pro` 对冻结的 6 个 case 进行了首次完整真实 API 评测。结果为
5 PASS、1 FAIL、0 provider error；Schema 成功率、decision 准确率和 Prompt Injection 拒绝率均为
100%，Skill policy 准确率为 83.33%。完整脱敏指标见
`evidence/llm_gateway/mimo_prompt_evaluation_v1.json`，原始逐样本文件只保存在本机
`~/.ros/robot_agent/mimo_planner_evaluation_v1/`。

唯一失败是 `route_preview_read_only`。模型正确选择了 `plan`，也包含必需的
`preview_safe_route`，但额外加入了 `query_semantic_target`，并向它传入
`target_x/target_y/target_yaw_deg`。该 Skill 的真实输入是 `map_profile + target_id`，因此这不是应当
放宽评测标准的“无害多一步”，而是通用 Plan Schema 无法表达逐 Skill 输入合约的架构缺口。

修复原则：

1. 保留 v0.1.0 的 5/6 基线，不覆盖、不重标；
2. 新 Prompt 版本向模型提供每个 Skill 的完整输入 JSON Schema；
3. Gateway 在模型返回后逐步执行本地 JSON Schema 校验，错误立即 fail closed；
4. 明确要求最小必要计划，坐标路径预览不应借用语义目标查询；
5. 修复后先定向复测失败 case，再运行完整套件；
6. 只有 Plan 与逐 Skill 输入双重合约通过后，才进入只读 Agent Loop。
