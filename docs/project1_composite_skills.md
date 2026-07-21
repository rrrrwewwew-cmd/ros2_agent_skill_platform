# 项目一能力接入与复合 Skill

## 仓库边界

项目一和项目二继续保持独立仓库。`robot_composite_skills@0.1.0` 不复制 GroundingDINO、Qwen-VL、
RGB-D 投影、语义地图或 Nav2 Keepout 源码；它只调用项目一安装态 Python/ROS 2 接口，并复用项目二
已经签名的四个原子 Skill adapter。

## `observe_and_avoid_water_risk`

固定顺序为：

```text
health(camera + scan)
  → project-one grounded risk observation
  → query water_puddle semantic map
  → preview Keepout-safe route
  → navigate with freshly derived path/map hashes
```

现场观察只有同时满足 `risk_found=true`、`landmark_updated=true` 和
`target_id=water_puddle` 才能继续。路径预览产生的 path hash 和语义地图 hash 直接传给导航 adapter，
不接受模型或用户伪造的“已批准路径”。

## `return_home_safely`

当语义地图已经存在时，固定顺序为：

```text
health(scan)
  → query water_puddle semantic map
  → preview Keepout-safe route
  → navigate with fresh evidence
```

两项复合 Skill 都是 `controlled`、非幂等、支持取消，并要求一次性精确 invocation 审批。外层审批
覆盖整个固定组合，但不会降低内部原子 adapter 的输入、权限、实时安全和后置条件检查。

## 失败关闭

- 健康检查失败：不查询、不规划、不运动；
- RGB-D/VLM/TF/语义地图失败：不规划、不运动；
- Keepout 路径不安全：不调用导航；
- 导航没有达到目标：组合结果失败；
- 结果 Schema、step 顺序或权限不匹配：Runtime 终止 run。

manifest 中声明的是组合过程可能使用的完整 ROS topic/service/action 并集。模块中的公开 entrypoint
函数本身会拒绝直接调用；只有 `SkillExecutor` 内的固定 `CompositeWorkflowAdapter` 可以执行该流程，
避免绕过 Registry、artifact、签名和一次性审批。

两个精确 artifact 已在 2026-07-20 完成现场感知预检、人工发布审批、Ed25519 签名与独立验签，
Registry 状态均为 `ACTIVE`。发布过程没有创建执行审批或发送运动命令；每次组合运动仍必须提交
完整 invocation，获得最长 300 秒、一次性消费的人工执行审批，并由 Runtime 重新验证 artifact 与
签名。现场完整运动闭环与失败关闭边界仍作为 release-candidate 收口项保留。
