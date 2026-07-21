# 版本化 RAG：可复算混合检索与晋级评测

## 1. 当前结论

`robot_rag@0.2.0` 已完成从确定性检索 smoke 到学习型 embedding A/B 的闭环。系统把 13 个官方或
项目事实来源冻结为 `robotics_core@1.1.0` 的 41 个 chunk，并同时保留两条检索路径：

- `feature_hash_v1`：无模型依赖、适合离线 CI 和回滚的确定性 baseline；
- `bge_m3_transformers_v1`：固定模型 revision 的多语言 dense embedding 候选。

新候选在从未运行过的 10-case holdout v3 上一次完成 10/10；baseline 为 8/10。候选的 Recall@K、
MRR、answerability、no-answer、版本过滤与引用完整性均为 100%，接口幻觉率为 0。该成绩只适用于
这个冻结小样本，不应表述为开放世界 100% 泛化。

## 2. 信任链

```text
source manifest + JSON Schema
  → content_file 限定在 corpus 根目录
  → source 原始字节 SHA-256
  → heading + sentence window 确定性分块
  → chunk text SHA-256
  → version-pinned embedding profile
  → terms + embedding vector
  → canonical index SHA-256
  → distribution/product/source_type filter
  → BM25 + embedding + abstention gates
  → source/version/content/chunk hash citation
  → frozen development / single-run holdout A/B
```

索引加载会重新验证 canonical hash、重复 chunk id、chunk 文本 hash、provider、维度、profile 与
retrieval policy。路径穿越、源文件变化、索引篡改、未知 filter、无效 `top_k`、模型元数据冲突均
fail closed。

## 3. 两种检索器

### 3.1 确定性 baseline

Baseline 使用 bilingual BM25 和 signed feature hashing。它不需要网络/GPU，输出可字节级复算，
但 feature hashing 不是学习型语义向量，不能把它包装为 semantic embedding。

### 3.2 BGE-M3 候选

`bge_m3_dense_v2` 固定：

- model：`BAAI/bge-m3`；
- revision：`5617a9f61b028005a4858fdac845db406aefb181`；
- 1024 维、CLS pooling、L2 normalize；
- `0.5 * normalized BM25 + 0.5 * dense cosine`；
- combined score 至少 0.25，embedding score 至少 0.48；
- BM25 不能绕过 embedding evidence gate；
- 语料未覆盖的技术标识符触发 `unsupported_identifier`，返回空引用。

学习模型是可选依赖，隔离在 `qwen_vl_env`，不会迫使 ROS/system Python 安装 PyTorch。模型只在本地
生成向量，不调用 MiMo，也不参与 Agent 决策。BGE-M3 官方模型卡说明其支持多语言、dense/sparse/
multi-vector 模式；本项目只采用 dense 路径并自行与 BM25 组合。

## 4. 拒答为什么是检索能力的一部分

只看 Recall 会奖励“什么都检索一点”的系统。这里把 no-answer 和接口幻觉列为晋级硬指标：

1. combined score 防止弱相关候选进入上下文；
2. embedding gate 防止关键词重叠单独越过门槛；
3. unknown identifier gate 拒绝语料未覆盖的接口/包/消息类型；
4. 普通英文复合词（如 `one-way`、`evidence-backed`）不属于技术标识符；
5. topic 路径和版本化模型名经过规范化匹配，例如 `safety_ok` 可匹配完整 topic，`Qwen-VL` 可
   匹配 `Qwen2.5-VL`。

这不是用规则回答问题；规则只决定“有没有足够证据把 chunk 交给下游 LLM”。最终引用仍绑定来源
版本和 hash。

## 5. 评测纪律与结果

| 数据集 | 用途 | Baseline | BGE-M3 v2 | 结论 |
| --- | --- | ---: | ---: | --- |
| development v2 | 16 answerable + 4 no-answer | 20/20 | 20/20 | 打平 |
| revealed v2 | 首次运行后降级为调参/回归集 | 8/10 | 10/10 | 仅回归证据 |
| holdout v3 | 8 answerable + 2 no-answer；只运行一次 | 8/10 | 10/10 | 候选晋级 |

holdout v3 上，baseline 的 no-answer accuracy 为 50%、interface hallucination rate 为 50%；BGE-M3
候选分别为 100% 和 0%。两者的版本过滤和 citation integrity 都是 100%。

失败历史没有删除：`bge_m3_dense_v1` 在首次 v2 评测中只有 8/10，Recall@K 和 MRR 均为 0.75，
未达到晋级门。该数据揭盲后不再称为 holdout；v2 修复必须先通过 development 和揭盲回归，随后
才允许运行新冻结的 v3 一次。

脱敏摘要位于 `evidence/rag/robotics_core_v2_bge_m3_ab.json`。本机完整 comparison、case CSV 和
索引位于 `~/.ros/robot_agent/rag/robotics_core_v2/`。

## 6. 复算命令

确定性 baseline：

```bash
cd ~/robot_agent_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 run robot_rag rag_build
ros2 run robot_rag rag_query \
  'semantic_keepout safety_ok 为 false 是否一定已经进入水坑？' \
  --distribution project1-v1 --top-k 3
```

本地 BGE-M3 索引：

```bash
cd ~/robot_agent_ws
PYTHONPATH=src/robot_rag:/usr/lib/python3/dist-packages \
HF_HOME=~/.cache/huggingface \
~/qwen_vl_env/bin/python -m robot_rag.build_cli \
  --manifest rag/corpora/robotics_core_v1/manifest.json \
  --embedding-profile rag/corpora/robotics_core_v1/profiles/bge_m3_dense_v2.json \
  --embedding-device cuda \
  --output ~/.ros/robot_agent/rag/robotics_core_v2/bge_m3_v2_index.json
```

评测命令接受 baseline/candidate index、冻结 manifest 和独立 output directory。Holdout 文件一旦
运行就必须原样保存，并在后续调参中降级为 development，不得反复运行挑最好成绩。

## 7. 能说什么，不能说什么

可以说：实现了版本化语料、hash-bound citation、确定性 baseline、固定 revision 的 BGE-M3 混合
检索、拒答策略、development/holdout A/B 和失败证据保留。

不能说：已经验证所有 ROS 问题、10 条 holdout 等于生产准确率 100%、BGE-M3 已接管生产 Agent，
或 RAG 已完成诊断闭环。下一步是把晋级后的 retriever 通过只读 MCP 工具接入实验诊断 Agent，并
继续用更大的冻结集扩展证据。
