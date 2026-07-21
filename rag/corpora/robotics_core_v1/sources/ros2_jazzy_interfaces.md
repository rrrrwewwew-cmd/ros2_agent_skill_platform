# ROS 2 Jazzy 通信接口事实卡

## Topic

Topic 用于连续数据流，采用异步 publish/subscribe；激光、相机、里程计和机器人状态通常属于此类。
消息是单向数据，不提供任务结果，也没有取消语义。

## Service

Service 用于短时同步 request/response，例如查询节点配置或触发一个能快速完成的计算。需要持续反馈、
运行较久或可取消的任务不应塞进 Service。

## Action

Action 用于长时任务。客户端发送 goal，执行期间可接收 feedback，最终得到 result，并且可以请求
cancel。移动机器人到目标位姿是 Action 的典型场景；接口定义分别使用 `.msg`、`.srv` 和 `.action`。
