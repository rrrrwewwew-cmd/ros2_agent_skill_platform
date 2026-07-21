# Skill Registry 与持久化 Agent 状态机

## 1. 为什么需要独立 Registry

LLM 输出的 Skill 名称不能直接等价于可执行能力。Registry 是运行时唯一可信目录，记录 Skill
版本、artifact hash、manifest、验证阶段、审批、签名和审计事件。Executor 只解析 `ACTIVE`
记录，并再次核对调用参数和动态前置条件。

## 2. 版本不可变

主键为 `name + version`。首次注册后，manifest 的 canonical JSON 和 artifact hash 都不可修改：

- 同一内容重复注册是幂等操作；
- 同一版本提交不同内容会被拒绝；
- 修改代码、依赖、manifest 或测试后必须使用新版本并重新走完整生命周期。

审批记录和签名都绑定 artifact hash，不能把旧版本审批复用到新二进制。

## 3. 生命周期与专用操作

```text
DRAFT → GENERATED → STATIC_VALIDATED → BUILT → UNIT_TESTED
      → SIMULATION_TESTED → HUMAN_APPROVED → SIGNED → ACTIVE → DEPRECATED
```

普通 `advance` 不能直接进入 `HUMAN_APPROVED` 或 `SIGNED`：

- `approve` 写入审批记录，并在同一事务进入 `HUMAN_APPROVED`；
- `skill_release verify-record` 用受信公钥验证 Ed25519 envelope 后调用事务记录，并进入 `SIGNED`；
- `ACTIVE` 只能来自带签名的 `SIGNED` 记录。

本地开发密钥保存在用户 ROS 数据目录且权限为 `0600`，不会进入 Registry、Trace 或 Git。生产环境
仍应把签名器迁移到 KMS/HSM。Runtime 会在每次调用前再次验签，所以伪造数据库状态不能绕过执行门。

## 4. SQLite 事务与并发

SQLite 使用 WAL、foreign keys 和 `BEGIN IMMEDIATE`。每次写操作必须携带调用者看到的
`expected_current_state`。事务取得写锁后重新读取状态；若另一进程已经推进，操作因 stale state
失败，而不是重复执行。

这种设计同时提供：

- 单机作品集环境的零服务依赖；
- 崩溃后持久化；
- 审批、签名和状态事件的原子写入；
- 后续迁移 PostgreSQL 时可保留相同事务语义。

## 5. Agent run 状态机

```text
IDLE → RETRIEVING → PLANNING → VALIDATING
     → WAITING_APPROVAL? → EXECUTING → VERIFYING → SUCCEEDED
```

各活动状态可进入 `FAILED` 或 `ABORTED`；任何非终止状态可进入 `EMERGENCY_STOP`。状态、request、
结构化 plan、trace id 和事件序列全部持久化。

进程重启时，不自动恢复可能已经产生副作用的 Agent Loop。`fail_closed_recover` 将遗留的活动 run
转为 `ABORTED` 并记录 `process_restart_fail_closed`，要求上层重新查询机器人真实状态后创建新
run。这牺牲自动续跑，换取不重复导航、地图修改或其他动作。

## 6. 当前边界

- Registry 不执行 Skill，只管理治理状态；
- 签名由独立 verifier 提供，Registry 只存已验证 envelope；
- SQLite 适合单机部署，不宣称多节点高可用；
- Agent 状态机不替代 Nav2 action 状态或 C++ safety monitor；
- MCP 和 LLM 后续只能调用该层提供的受限方法。
