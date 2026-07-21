# Skill 发布签名与运行时验签

## 1. 目标

Registry 状态不是代码身份本身。某个 Skill 即使被标成 `ACTIVE`，运行时仍必须证明本地 artifact
与发布者批准的是同一份内容。本项目使用以下链路：

```text
artifact file list
  → sha256-file-list-v1
  → approval bound to artifact_hash
  → Ed25519 signature envelope
  → external verification and Registry SIGNED
  → ACTIVE
  → Runtime verifies hash and signature again before adapter invocation
```

签名覆盖 Skill 名称、版本、artifact hash、hash 算法、签名人、创建时间和公钥指纹。任一字段变化
都会使验签失败。Registry 保存规范化 JSON envelope，不保存私钥。

## 2. 本地开发密钥

生成 Ed25519 密钥：

```bash
ros2 run robot_skill_registry skill_release keygen \
  --private-key ~/.ros/robot_agent/keys/release_ed25519.pem \
  --public-key ~/.ros/robot_agent/keys/release_ed25519.pub.pem
```

私钥被写为 `0600`，加载时若存在 group/other 权限会 fail closed。当前未加密 PEM 仅用于单机作品集
和开发环境；生产部署应改用 Secret Manager、KMS 或 HSM，并把公钥或指纹固定在部署配置中。

## 3. 签名与验证后登记

签名器会先重新计算 artifact lock，不允许为缺失、越界、被修改或 hash 不匹配的文件签名：

```bash
ros2 run robot_skill_registry skill_release sign \
  --repository-root ~/robot_agent_ws \
  --name check_robot_health \
  --version 0.2.0 \
  --artifact-hash <SHA256> \
  --private-key ~/.ros/robot_agent/keys/release_ed25519.pem \
  --signer local_release_authority \
  --output ~/.ros/robot_agent/releases/check_robot_health-0.2.0.json
```

验证器使用受信公钥重新检查 envelope、签名和本地 artifact，然后才调用 Registry 的事务操作：

```bash
ros2 run robot_skill_registry skill_release verify-record \
  --db ~/.ros/robot_agent/registry.db \
  --repository-root ~/robot_agent_ws \
  --envelope ~/.ros/robot_agent/releases/check_robot_health-0.2.0.json \
  --public-key ~/.ros/robot_agent/keys/release_ed25519.pub.pem \
  --reason "Ed25519 release proof verified"
```

旧的“任意字符串直接登记签名”CLI 已移除。底层 Registry 仍只负责事务记录，密码学验证由独立发布
模块负责，便于以后替换为组织级签名服务。

## 4. Runtime 的第二道验证

`skill_execute` 默认信任：

```text
~/.ros/robot_agent/keys/release_ed25519.pub.pem
```

也可通过 `--trusted-public-key` 显式指定。Runtime 在固定适配器启动前依次检查：

1. Registry 状态为 `ACTIVE`；
2. invocation、Registry 和 artifact lock 的 hash 一致；
3. 本地文件重新计算的 hash 一致；
4. Registry envelope 的身份、指纹和 Ed25519 签名通过受信公钥验证；
5. 输入 Schema、ROS 权限和固定 adapter 一致。

因此，仅修改数据库状态或塞入伪造 signature 不能获得执行能力。失败会进入持久化 AgentRun
`FAILED`，并写入 JSONL Trace，但 Trace 不记录密钥材料。

## 5. 审批语义

`HUMAN_APPROVED` 是当前 Registry 生命周期中的审批态。对
`requires_human_approval: true` 的 Skill，只允许真实人工审批；对本项目的只读健康检查，manifest
明确声明 `requires_human_approval: false`，可由记录清晰的只读发布策略 actor 批准。无论审批来源，
签名和 Runtime 验签都不能省略。后续高风险导航 Skill 必须保留人工 diff 审批。
