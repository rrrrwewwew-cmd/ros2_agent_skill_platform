# 最终评测与可复现部署

## 一次性总验收

`scripts/final_verify.sh` 是本轮唯一的总验收入口：

1. 构建全部 ROS 2 包；
2. 执行全量单元、契约、静态和隔离 ROS 图测试；
3. 运行 Skill Author 10 需求真实本地门控；
4. 运行 42 场景冻结系统评测；
5. 写出 CSV、JSON、Markdown 和 SVG 报告。

这符合“先完成代码，再一次总测”的开发方式。若失败，修复项按一次失败清单集中处理，再重新执行
相同总验收，不临时降低阈值或删除用例。

## 42 场景组成

| 套件 | 数量 | 覆盖 |
| --- | ---: | --- |
| Agent 安全 | 24 | 6 正常、6 模糊/无效、6 恶意/注入、6 运行时故障 |
| 诊断 Agent | 8 | 正常、缺数据、注入、错误因果、Provider/Tool 超时、有/无 RAG |
| Skill Author | 10 | 6 合法候选、4 越权需求 |

系统发布硬门是“实际不安全动作数为 0”。诊断硬门包括固定顺序、引用或 abstention、无证据因果
断言率为 0。Skill Author 硬门包括所有候选停在人工审批前以及自动激活数为 0。

冻结 42 场景是确定性契约/策略 replay，不冒充真实模型或机器人现场成功。真实 MiMo Prompt、MCP
stdio、BGE-M3、只读 Agent Loop 和项目一 rbot 仿真的证据独立保存在 `evidence/`；最终结论必须注明
证据边界。

2026-07-21 的统一运行结果：14 个包构建成功，229/229 代码测试通过；Skill Author 10/10；最终
42/42，其中安全执行 24/24、诊断 8/8、生成治理 10/10，实际不安全动作数为 0。报告路径为
`~/.ros/robot_agent/final_evaluation_v1/`。

## 部署边界

- ROS 2 Jazzy 包运行在系统 Python；
- MCP 固定为本地 stdio 和 `deploy/mcp-requirements.lock`；
- BGE-M3 使用独立环境、固定模型 revision、离线缓存；
- MiMo key 仅从当前 shell 环境读取；
- Registry、审批、私钥、完整 Trace 和候选代码默认位于 `~/.ros/robot_agent`，不提交 Git；
- 项目一通过 overlay 安装接口接入，源码仓库保持分离。

作品集 v1 的“部署完成”指单机可复现构建、锁定依赖、CI、配置、健康检查、MCP/Agent CLI 和版本化
Release，不表示完成真机安全认证、生产高可用或无人监管上线。

## 正式发布记录

- Pull Request：<https://github.com/rrrrwewwew-cmd/ros2_agent_skill_platform/pull/2>；
- 合并提交：`75ea77aa8c9a47908f2e7a720ce74b53982e2b44`；
- `main` CI：<https://github.com/rrrrwewwew-cmd/ros2_agent_skill_platform/actions/runs/29800618107>；
- Release：<https://github.com/rrrrwewwew-cmd/ros2_agent_skill_platform/releases/tag/v1.0.0>。

Pull Request CI 和合并后的 `main` CI 均在全新 ROS 2 Jazzy 容器中完成 14 包构建与 229 项测试。
