# Nav2 Keepout Filter 事实卡

## 数据面

Nav2 KeepoutFilter 通过 OccupancyGrid filter mask 和 CostmapFilterInfo 元数据解释禁区。Keepout 类型
为 0；info server 的 `mask_topic` 必须与用于发布 mask 的 map server topic 对齐。

## 全局与局部代价地图

只在 global costmap 启用 KeepoutFilter，会让全局规划器绕开禁区；只在 local costmap 启用时，全局
路径仍可能穿过禁区，只是控制阶段拒绝进入。需要“规划绕行 + 执行保护”时，应在两者中一致启用并
验证各自订阅的 filter info。

## 几何安全边界

Costmap filter 本身不会自动获得普通 inflation layer 的膨胀语义。规划器、机器人 footprint、定位
误差和跟踪误差需要单独考虑；不能仅凭禁区中心栅格为 lethal 就宣称整条路径有足够净空。
