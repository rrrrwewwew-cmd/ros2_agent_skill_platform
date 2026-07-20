# ROS 2 Humble QoS 版本干扰卡

## 评测用途

本来源只用于测试 distribution filter，不能回答要求 ROS 2 Jazzy 的问题。即使 QoS 关键词高度相似，
查询过滤条件为 `distribution=jazzy` 时也必须排除此 Humble 来源。

## 版本规则

检索系统不能把“主题相似”当作“版本正确”。回答发行版相关问题时，citation 必须携带 source id、
version、distribution、内容 hash 和 chunk hash，以便调用方拒绝错误版本。
