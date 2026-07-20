# ROS 2 Jazzy tf2 与时间事实卡

## 时间化坐标变换

tf2 在带时间的缓冲区中维护坐标系树。查询 transform 时，source frame、target frame 和时间戳共同
决定结果；“当前存在 TF”不能证明某个历史传感器时间戳也可转换。

## extrapolation 排障

`extrapolation into the past` 表示请求时间早于缓冲区可用数据，`extrapolation into the future` 表示
请求时间晚于可用数据。应检查消息时间戳、`/clock`、各节点的 `use_sim_time`、TF 发布频率和缓冲区
覆盖范围，而不是随意改成最新 TF 掩盖时序错误。

## 仿真时钟

仿真系统必须让相关 ROS 2 节点一致使用 simulation time。Gazebo 重启或残留发布者可能造成时钟回退
和 `TF_OLD_DATA`；运行隔离、唯一仿真分区和完整关闭旧进程有助于避免混合两条时间线。
