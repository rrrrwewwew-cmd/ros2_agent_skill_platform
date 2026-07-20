# 项目二 Agent Loop 与 Trace 事实卡

## 父子运行

一次 Agent 任务有父 `run_id` 与 `trace_id`；每个 Skill step 使用独立子 run 和子 Trace。父结果记录
计划、step 状态、输入 SHA-256、artifact hash、evidence gate 和子 trace file，从而关联 LLM 计划与
确定性工具证据。

## 状态与停止条件

Agent 按顺序执行只读步骤。任一步出现契约错误、Runtime 失败或不安全 evidence，后续步骤不运行；
状态应区分 succeeded、failed、refused、clarification 和 blocked_by_evidence，而不是只写一条自然
语言总结。

## 可观测性边界

JSONL Trace 是 append-only 审计记录，但不得包含 API key 或签名私钥。工具返回的 succeeded 只证明
调用完成；是否继续由本地 evidence gate 判断，不能交给 MiMo 自我评判。
