# ROS 2 Jazzy QoS 事实卡

## 兼容性与排障

ROS 2 publisher 和 subscription 的 QoS 必须兼容，否则图上即使能看到发布者，订阅者也可能收不到
消息。排障时应同时检查 reliability、durability、history 和 depth，不能只检查 topic 名称和消息类型。

## 传感器数据

传感器数据通常强调及时获得最新样本，因此 ROS 2 的 sensor data profile 使用 best effort
reliability 和较小队列。订阅激光雷达、相机或 IMU 时，应先核对发布端实际 QoS，再选择兼容策略。

## 持久化状态

需要让后加入的订阅者收到最近状态时，可使用 transient local durability；这类似持久化最近样本。
volatile durability 不会为后加入订阅者保留历史。服务请求应避免使用会重放旧请求的持久化策略。
