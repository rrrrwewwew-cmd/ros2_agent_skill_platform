# Nav2 Jazzy 规划与导航 Action 事实卡

## ComputePathToPose

`nav2_msgs/action/ComputePathToPose` 只请求规划器计算从起点到目标位姿的 `nav_msgs/Path`。Goal 包含
目标 `PoseStamped`、可选起点、`planner_id` 和 `use_start`；Result 包含 path 与 planning time。
成功拿到路径不表示机器人执行了移动。

## NavigateToPose

`nav2_msgs/action/NavigateToPose` 是执行导航的高层 Action，会进入行为树、控制器、恢复行为与障碍物
处理。它与只读路径预览不是同一种权限；Agent 的 read-only Skill 只能调用
`/compute_path_to_pose`，不能把规划成功解释成导航成功。

## 安全预览

安全预览还要验证目标误差、路径长度、路径与动态 Keepout 的最小净空、全局代价地图中心 cost 以及
语义地图内容 hash。只有这些确定性证据均通过时，输出才可标记 `safe_to_execute=true`；该字段仍不
等于执行授权。
