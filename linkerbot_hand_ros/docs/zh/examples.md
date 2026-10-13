# 命令与 Python 示例

[English](../examples.md) | [使用手册](../../README_zh.md)

先按[快速开始](getting_started.md)激活驱动。以下单手路径为 `/linkerbot_hand`；多手请替换为保存的 namespace。

## 读取能力和反馈

```bash
ros2 topic echo --once /linkerbot_hand/capabilities
ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/angles
ros2 topic echo /linkerbot_hand/command/status
```

由 verified capability 确认关节顺序、范围和支持命令。反馈需检查 `valid`、`stale`、
`connection_generation` 及逐轴有效性；到位判据见[业务集成](business_integration.md)。

## 发送一个 O6 角度目标

以下命令会移动六轴 O6；确认空间和目标后执行。其他型号按 capability 提供数组，
L6 还需满足[位置模式要求](ros_api.md#l6-力矩输出模式)。

```bash
ros2 topic pub --once /linkerbot_hand/command/angles \
  linkerbot_hand_msgs/msg/HandJointCommand \
  '{client_id: 1, user_sequence: 1, representation: 1, values: [50, 50, 50, 50, 50, 50]}'
```

`representation: 1` 是 percent，屈伸轴 `0=弯曲、100=伸直`；侧摆/旋转轴看端点标签。
`representation: 2` 是协议 raw，必须符合逐轴范围及整数约束，不执行物理单位转换。
同一发布者每次使用新的 `user_sequence`，不同发布者使用不同非零 `client_id`。

`command/status` 是批消息，遍历 `statuses[]` 并按 `(client_id, user_sequence)` 匹配。
无 ACK 的命令以 `DISPATCHED` 成功终止，有 ACK 的命令等待 `ACKNOWLEDGED`；
`FAILED`、`SUPERSEDED` 都不是机械到位。SDK 接受前的拒绝还需查看 `/diagnostics`。

## 读取设置

驱动只创建 capability 支持的端点。例如 O6 主动查询配置速度：

```bash
ros2 service list -t
ros2 service call /linkerbot_hand/get_configured_speeds \
  linkerbot_hand_msgs/srv/GetRawValues '{timeout_s: 0.5}'
```

同名服务在不同型号上可能查询设备、读取设备写回包或读取本地命令缓存。
`success=true` 不代表新鲜实测值；检查 `state.meta`、`raw_unit` 和 `raw_scale_note`。
完整读写端点及缓存约定见 [ROS API](ros_api.md#按需读取配置与限制状态)，型号差异见[型号指南](models.md)。
不要把配置速度、电流限制或转矩限制用于实时反馈闭环。

## 常驻 Python 客户端

业务节点持有一个 `HandCommandClient`，复用发布器和订阅；节点必须持续 spin。
以下方法接入已有业务 Node，由业务提供已校验目标，在低频 ROS 异步回调中调用：

```python
from linkerbot_hand_msgs.msg import HandCommandStatus
from linkerbot_hand_ros.client import HandCommandClient


def init_hand(self):
    self.hand = HandCommandClient(self, "/linkerbot_hand")


async def send_target(self, target_percent):
    if not await self.hand.wait_until_ready_async(2.0):
        return False
    publication = self.hand.set_percent_angles(target_percent)
    status = await self.hand.wait_for_terminal_status_async(
        publication.user_sequence, 1.0
    )
    return status is not None and status.stage in (
        HandCommandStatus.STAGE_DISPATCHED,
        HandCommandStatus.STAGE_ACKNOWLEDGED,
    )
```

返回值只表示协议发送成功；业务仍需独立判断机械到位。参数错误会抛出异常，按业务错误策略处理。
销毁 Node 前调用 `self.hand.destroy()`。高频 timer 用 `is_ready("angles")`、发布和后续 tick 的
`get_status(sequence)` 组成非阻塞状态机。不要在单线程 executor 回调中同步等待，
也不要嵌套 spin；详见[客户端等待](client_waits.md)。

随包工具：`state_monitor` 观察状态，`angle_command --values ...` 发送指定角度，
`angle_controller` 用于常驻控制；参数用各工具的 `--help` 查看。

## 触觉、管理与恢复

按[触觉指南](force.md)开启所需轮询；六种矩阵型号订阅 `state/tactile`，O30 订阅
`state/tactile_sensors`，不能把单指、cell 或 CAN 分片计为完整采样。

```bash
ros2 service call /linkerbot_hand/get_device_info \
  linkerbot_hand_msgs/srv/GetDeviceInfo '{timeout_s: 0.2}'
ros2 service call /linkerbot_hand/recover \
  linkerbot_hand_msgs/srv/Recover '{timeout_s: 1.0}'
```

恢复前停止业务目标；成功后等待新连接代次的有效反馈，再显式产生新目标。
堵转、增益、清错和保存参数的能力及使用边界见[型号指南](models.md)；
服务接受写命令后，按返回的 `command_id` 追踪协议终态。
