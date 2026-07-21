# 项目一动态语义 Keepout 接口事实卡

## 风险数据流

项目一在 rbot 仓库中使用 GroundingDINO 定位水坑候选，确定性颜色、深度和物理尺寸规则执行门控，
Qwen2.5-VL 对已接受事件解释移动机器人安全策略。同帧 RGB-D 候选经过时间戳 TF 投影后写入持久化
语义地图，供动态 Keepout 使用。

## ROS 2 接口

逻辑禁区 mask 发布在 `/local_keepout_filter_mask`，类型为 `nav_msgs/msg/OccupancyGrid`。独立 C++
安全监控读取 mask、`/tf` 和 `/tf_static`，发布 `/diagnostics` 与
`/semantic_keepout/safety_ok`。监控器是只读的，不发布速度，也不改变 Nav2 规划或控制。

## fail-closed 语义

`/semantic_keepout/safety_ok=false` 不只表示机器人已经进入禁区；输入缺失、数据过期、坐标未知、
机器人越出 mask 或位于占用栅格时也不能建立安全性。下游 Agent 必须停止继续运动，不能把 unknown
当作 safe。

## rbot 水坑 profile

`rbot_water_puddle_v2` 使用持久化水坑位置和 0.60 m 逻辑风险半径。路径预览还要检查全局代价地图
中心 cost、路径与风险圆的线段距离、语义地图内容 hash，并明确证明没有发送运动命令。
