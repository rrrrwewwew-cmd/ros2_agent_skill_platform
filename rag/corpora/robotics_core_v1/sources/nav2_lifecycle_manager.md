# Nav2 Lifecycle Manager 事实卡

## 确定性启动

Nav2 Lifecycle Manager 按配置顺序把受管节点从未配置状态转入配置和 Active，并在关闭时按相反顺序
处理。导航前应确认受管节点已 Active，而不是只检查进程是否存在。

## Bond 与故障

Lifecycle Manager 使用 bond 监测服务器。节点无响应或崩溃时，管理器会为安全关闭相关受管节点；
`bond_timeout` 和 respawn 重连参数决定检测与恢复行为。健康检查应读取管理器的活动状态或生命周期
服务证据。

## Agent 使用边界

LLM 不能根据日志中的“process started”推断 Nav2 已可用。Agent 应调用确定性的健康 Skill，并把
Active 状态、TF 新鲜度和安全监控结果作为后续规划或运动的前置证据。
