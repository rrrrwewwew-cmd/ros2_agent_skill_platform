# 版本化 RAG：首个可复算检索切片

## 1. 目标与边界

`robot_rag@0.1.0` 先建立可信知识数据面，再让 LLM 使用检索结果。它当前不调用 MiMo、不访问网络，
也不读取任意文件。输入是仓库内冻结的 source manifest，输出是带 source/version/content/chunk hash
的结构化引用。

首版语料不是整页网页镜像，而是由官方来源和项目事实整理出的短事实卡。manifest 保留 canonical
URL、发行版、产品、版本和检索日期；本地事实卡字节必须匹配 SHA-256。这样既能离线重放，也能在
上游文档变化时显式发布新 source version，而不是悄悄覆盖旧索引。

## 2. 信任链

```text
source manifest JSON Schema
  → content_file 路径限制在 corpus 根目录
  → 每个文件原始字节 SHA-256
  → Markdown heading + sentence window 确定性分块
  → chunk text SHA-256
  → terms + feature_hash_v1 vector
  → canonical index SHA-256
  → 查询发行版/产品过滤
  → BM25 + feature hash 排序
  → source/version/content/chunk 引用
```

索引加载时会重新验证 canonical index hash、重复 chunk id、chunk 文本 hash 和向量维度。manifest
路径穿越、源文件改变、索引手工修改、未知 filter、超长查询或越界 `top_k` 均 fail closed。

## 3. 检索算法

当前离线基线使用两个确定性通道：

1. bilingual BM25：英文/ROS 标识符 token 与中文双字 token；
2. `feature_hash_v1`：token 与字符三元组经过固定维度 signed feature hashing 后计算 cosine。

最终分数为 `0.65 * normalized_bm25 + 0.35 * feature_hash_cosine`。Feature hashing 不是学习型语义
embedding，不能把当前结果描述为“向量语义检索质量”。它的作用是提供零模型下载、可重复 CI 和
未来 learned embedding A/B 的确定性 baseline。

## 4. v1 语料与评测

`robotics_core@1.0.0` 当前包含 7 个来源、22 个 chunk：

- ROS 2 Jazzy QoS 与 tf2/time；
- Nav2 Lifecycle Manager 与 KeepoutFilter；
- 项目一动态语义 Keepout 公开接口；
- 项目二 Skill/Runtime/approval 治理契约；
- 一个仅用于评测 distribution filter 的 ROS 2 Humble 干扰源。

8-case smoke set 覆盖 QoS、TF extrapolation、Lifecycle、Keepout global/local、项目一 topic、
fail-closed 和受控 Skill。安装态结果为 Recall@K 100%、MRR 100%、版本过滤 100%、引用完整性
100%。这只证明最小数据链和测试装置工作，不代表已经满足 Phase 2 的 30-query 质量门槛，也不代表
面对开放问题的泛化能力。

## 5. 命令

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 run robot_rag rag_build

ros2 run robot_rag rag_query \
  'semantic_keepout safety_ok 为 false 是否一定已经进入水坑？' \
  --distribution project1-v1 \
  --top-k 3

ros2 run robot_rag rag_evaluate \
  --output-dir ~/.ros/robot_agent/rag/robotics_core_v1/evaluation
```

默认索引写入 `~/.ros/robot_agent/rag/robotics_core_v1/index.json`。索引和评测输出属于本机可再生
artifact；Git 只保存 manifest、事实卡、评测集和脱敏摘要。

## 6. 下一阶段

先把评测扩展到至少 30 个冻结查询，并分开 development 与 holdout；随后加入版本锁定的多语言学习型
embedding provider，与当前 deterministic baseline 做 A/B。完成 no-answer、错误发行版、引用正确性
和接口幻觉评测后，RAG 才能进入 MCP 诊断 Agent 和 Skill Author Prompt。
