# `preview_safe_route` 只读安全路径预览 Skill

## 1. 为什么规划 Action 仍可归为只读

`/compute_path_to_pose` 接收一个 Action goal，但结果只是 `nav_msgs/Path`，不会发送
`NavigateToPose`、发布 `/cmd_vel` 或改变机器人状态。因此该 Skill 的物理副作用为零，清单权限也只
包含规划 Action 和全局代价地图查询 Service。

```text
bounded goal + keepout_profile
  → manifest input Schema
  → fixed SafeRoutePreviewAdapter
  → approved semantic-map profile
  → /global_costmap/get_costmap
  → /compute_path_to_pose (use_start=false)
  → path geometry + endpoint + Keepout policy
  → result Schema + Runtime semantic postconditions
```

项目一的 `semantic_keepout_trial` 已证明路径长度和禁区间距计算有效，但它随后调用 `goToPose`。项目二
没有复用那个可运动 CLI，而是只复用稳定接口思想并建立独立只读实现。

## 2. 三个相互独立的安全条件

返回 `safe` 必须同时满足：

1. Nav2 成功返回 `map` 坐标系路径，且路径终点距离请求目标不超过 0.25 m；
2. 语义风险中心在当前全局 master costmap 中的 cost `>=253`，证明 Keepout 过滤器实际生效；
3. 对整条折线路径逐段计算后，最小净空严格大于零，不穿过持久化语义风险圆。

仅“Nav2 返回了路径”不构成安全结论。规划器、仿真时钟、代价地图或语义地图任一证据缺失时都返回
`unavailable`；策略不满足则返回 `unsafe`。所有状态都固定包含
`motion_command_sent=false`。

## 3. 受限输入与输出证据

初始版本只接受：

- `goal_x`、`goal_y`：`[-20, 20]` m；
- `goal_yaw_deg`：`[-180, 180]`；
- `keepout_profile=rbot_water_puddle_v2`。

Agent 不能选择文件路径、risk id、半径、planner id、Action 名、Service 名或 ROS namespace。输出记录
路径长度、pose 数、起终点、终点误差、路径 SHA-256、语义地图内容 SHA-256、禁区几何、中心 cost、
最小净空、规划耗时和观测时间。

## 4. 仍然不能直接导航

路径预览是一份瞬时证据，不是对未来环境的预约。后续 `navigate_to_approved_pose` 属于 controlled
Skill，必须重新检查机器人健康、Keepout 和目标边界，并经过更严格审批；不能把旧的 `safe` 结果直接
转换成运动授权。
