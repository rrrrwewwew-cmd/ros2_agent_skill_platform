# 项目二 MiMo LLM Gateway 事实卡

## 单 Provider

生产规划后端只有 Xiaomi MiMo Chat Completions；`FakeProvider` 只用于离线 CI，不是第二个生产 API。
密钥只从 `MIMO_API_KEY` 读取，不能写入 Prompt、Trace、Git 或 RAG 语料。

## Prompt 与本地门控

Prompt 按 id、version 和 canonical SHA-256 锁定。用户任务作为不可信 JSON 与 system rules、冻结
Skill catalog 分离。模型输出必须通过 Agent Plan JSON Schema，再逐步核对 Skill name、version、
artifact hash、连续 step id 和输入 Schema；任何不一致都 fail closed。

## 权限边界

Gateway 只返回 plan，不导入 Skill Runtime，也不调用 ROS 2。当前模型 catalog 只暴露三个只读
Skill；`navigate_to_approved_pose` 对模型不可见，因此 Tool Calling 规划不能绕过受控运动审批。
