# MCP diagnosis evidence

- `diagnosis_mcp_stdio_v1.json`：官方 MCP 1.28.1 + deterministic RAG 的五工具 stdio 回归；
  检索拒答，证明无证据不会伪造引用。
- `diagnosis_mcp_bge_m3_stdio_v1.json`：相同协议与工具契约，通过隔离 BGE-M3 子进程获得 3 条
  hash-bound citations，并生成幂等报告。

两份证据均记录 ToolAnnotations、input/evidence hash、报告 artifact hash 和源实验 snapshot hash。
模型权重、完整索引、原始运行数据库和本机路径下的报告不提交 Git。
