# 实验诊断 MCP 垂直切片

## 1. 交付结论

`robot_diagnosis_mcp@0.1.0` 已把冻结实验日志、确定性 Python 分析和版本化 RAG 暴露为五个
有界 MCP Tool，并通过官方 Python SDK 的真实 stdio 会话完成 `initialize → list_tools →
call_tool` 协议回归。该切片仍是诊断数据面，不是最终 MiMo 诊断 Agent：模型编排、持久状态机和
诊断 A/B 属于下一里程碑。

MCP 采用官方 Python SDK `1.28.1`。官方说明 v1 是当前稳定线、v2 仍处于 alpha，并建议依赖使用
`mcp>=1.27,<2`，所以本包没有提前迁移到 v2：

- [MCP Python SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
- [MCP 1.28.1 包元数据](https://pypi.org/project/mcp/1.28.1/)

## 2. 技术路线

```text
MCP client / future diagnosis Agent
  │  local stdio JSON-RPC; no listening port
  ▼
Official FastMCP protocol adapter
  │  typed inputs + ToolAnnotations
  ▼
SDK-independent DiagnosisToolService
  ├─ allowlisted experiment root → verified manifest/source hashes
  ├─ safe_agent_core → distance matrix/anomaly/control correlation
  ├─ deterministic RAG adapter → offline CI and abstention
  ├─ isolated BGE-M3 process → learned retrieval with citations
  └─ independent artifact root → JSON/SVG/Markdown report
```

协议适配器和业务实现分离有两个原因：普通 ROS 2 CI 不需要安装 MCP SDK；工具的路径、hash、
Schema 和因果边界可以用纯 Python 快速测试。只有协议测试进入专用 `robot_agent_mcp_env`，验证
真实 JSON-RPC 和 SDK 行为。

## 3. 五个 Tool 契约

| Tool | 权限 | 关键输入 | 输出与证据门 |
| --- | --- | --- | --- |
| `list_experiment_runs` | read-only | 无 | 只列出根目录内 hash 验证通过的 run |
| `inspect_experiment_run` | read-only | allowlisted `run_id` | manifest、frame、time base、逐源 hash/size |
| `analyze_experiment_run` | read-only | `run_id` | 矩阵维度/hash、异常窗、控制证据、候选机制 |
| `retrieve_robotics_knowledge` | read-only | query、distribution、top-k≤3 | 版本过滤、引用或显式 abstain |
| `materialize_diagnosis_report` | artifact-write | run、1–3 个知识查询 | 幂等派生报告；不修改源日志 |

前四项的 MCP annotation 为 `readOnly=true, destructive=false, idempotent=true,
openWorld=false`。第五项只允许在独立 artifact root 写派生文件，标记为非只读但
`destructive=false, idempotent=true, openWorld=false`。它不是“对外发布”：后续若把报告发送到
远端或交给他人，仍需独立人工审批。

所有工具统一返回 `mcp_tool_result.schema.json`：

- tool name/version 与 safety class；
- canonical input SHA-256；
- canonical evidence SHA-256；
- 结构化 evidence；
- RAG source/chunk hash、版本和 canonical URL。

完整矩阵不会塞进 LLM 上下文。Tool 只返回矩阵维度、样本时间戳和矩阵 hash；完整值进入派生
`analysis.json`。这同时限制上下文规模并保留复算能力。

## 4. 文件与模型隔离

- run 只能按正则化 id 从已经验证的目录 catalog 中选择，不能传路径；
- manifest 中任意 source hash 不一致时整个 catalog fail closed；
- 报告目录由 `run_id + bundle_sha256` 决定，重复请求返回相同 artifact hash；
- BGE-M3 不加载进 MCP 服务器进程，而由固定 Python、固定 module path 和固定 index 启动；
- 子进程不使用 shell，不继承 HTTP(S) proxy，不接收任意命令；
- `HF_HUB_OFFLINE=1` 和 `TRANSFORMERS_OFFLINE=1` 强制只读本地固定 revision 缓存。

开发时曾出现学习型检索 120 秒超时。最小复现表明，精简环境删除代理后 Transformers 仍尝试
访问 Hub 元数据；它没有网络却没有进入离线模式。修复不是重新开放代理，而是强制离线加载。
修复后同一 BGE-M3 查询在约 6–9 秒完成并返回 3 条 hash-bound citations。

另一个真实协议问题是对虚拟环境 Python 使用 `Path.resolve()`：它会把 `venv/bin/python` 符号链接
折叠成系统解释器，悄悄丢失隔离依赖。实现现在只转为绝对路径，不解析符号链接，并有回归测试。

## 5. 安装与启动

官方 SDK 放在独立环境，不污染 Qwen-VL、GroundingDINO 或 ROS 2 系统 Python：

```bash
python3 -m venv --system-site-packages ~/robot_agent_mcp_env
~/robot_agent_mcp_env/bin/python -m pip install 'mcp>=1.27,<2'
```

服务器只走本地 stdio；命令必须显式给出四个信任根：

```bash
cd ~/robot_agent_ws
PYTHONPATH=src/robot_diagnosis_mcp:src/robot_rag:src/safe_agent_core \
  ~/robot_agent_mcp_env/bin/python -m robot_diagnosis_mcp.server_cli \
  --experiment-root ~/robot_agent_ws/examples \
  --artifact-root ~/.ros/robot_agent/diagnosis_mcp_artifacts_v1 \
  --rag-index ~/.ros/robot_agent/rag/robotics_core_v1/index.json \
  --schema-dir ~/robot_agent_ws/schemas
```

学习型检索再增加固定 `--rag-python`、两个 module root、`--embedding-device cuda` 和 HF cache。
完整可复算命令保存在 `robot_diagnosis_mcp.protocol_smoke --help` 及本文件对应 Git 版本中。

## 6. 验证证据

- 包级测试：16/16；路径逃逸、hash 篡改、distribution/top-k 越界、幂等、源文件不变、离线环境
  和虚拟环境入口均覆盖；
- 全工作区：10 个 ROS 2 包、199 tests、0 errors/failures/skipped；
- baseline stdio：五工具通过，feature-hash 对不充分查询正确 abstain；
- BGE-M3 stdio：五工具通过，retrieval/report 各 3 条引用；
- MCP SDK：1.28.1；协议：2025-11-25；AnyIO：4.14.2；
- 两次协议回归均确认 7 个实验源文件前后 snapshot hash 完全相同。

机器证据：

- `evidence/mcp/diagnosis_mcp_stdio_v1.json`
- `evidence/mcp/diagnosis_mcp_bge_m3_stdio_v1.json`

当前限制：只有一个冻结抖动 run；真实 stdio 在当前自动化沙箱内受异步线程生命周期限制，因此
协议证据在同一 WSL 主机的沙箱外执行。AnyIO 4.14.2 在该实际执行边界已通过，不能把沙箱现象
误写成 SDK 版本缺陷。
