# 控制与 Python 示例

先按[快速开始](quick_start.md)激活驱动。多手使用实际路径替换 `/linkerbot_hand`；所有数组顺序与范围来自设备能力。

## 读取能力和反馈

```bash
ros2 topic echo --once --qos-durability transient_local /linkerbot_hand/capabilities
ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/angles
ros2 topic echo /linkerbot_hand/command/status
```

确认身份已验证、角度 `meta.valid=true`、`stale=false`，连接代次正确。逐轴检查 `percent_valid`；L6 使用角度前还须确认[位置模式](l6.md#型号差异与管理)。

## 发送一个 O6 角度目标

以下命令会移动六关节 O6。先核对机械空间、当前角度与方向，再执行：

```bash
ros2 run linkerbot_hand_ros angle_command --values 50 50 50 50 50 50
```

默认 percent 为 0..100；屈伸轴 0 表示弯曲端，100 表示伸直端，其他轴按能力端点解释。用 `--raw --values ...` 发送精确协议整数。工具等待驱动就绪并检查协议终态，不判断机械到位。

直接发布 ROS 消息时显式填写关联 ID：

```bash
ros2 topic pub --once --qos-reliability best_effort \
  /linkerbot_hand/command/angles linkerbot_hand_msgs/msg/HandJointCommand \
  '{client_id: 1, user_sequence: 1, representation: 1, values: [50, 50, 50, 50, 50, 50]}'
```

每个发布者用不同的非零 `client_id`，每条命令用新 `user_sequence`。该命令未填 `publisher_stamp`，不能测发布延迟。正式业务使用客户端自动填写。

## 可运行的 Python 客户端

在已加载 ROS 环境的终端保存为 `hand_command_example.py`，运行 `python hand_command_example.py`。示例将全部关节设为 50 percent，会移动设备；先完成上述状态检查，并将 target 替换为业务目标。

```python
import threading

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node

from linkerbot_hand_msgs.msg import HandCommandStatus
from linkerbot_hand_ros.client import HandCommandClient


def main():
    rclpy.init()
    node = Node("hand_command_example")
    hand = HandCommandClient(node, "/linkerbot_hand")
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def spin():
        try:
            executor.spin()
        except ExternalShutdownException:
            pass

    worker = threading.Thread(target=spin)
    worker.start()
    try:
        if not hand.wait_until_ready(2.0):
            raise RuntimeError("Driver is not ready")
        target = [50.0] * len(hand.joint_names)
        publication = hand.set_percent_angles(target)
        status = hand.wait_for_terminal_status(publication.user_sequence, 1.0)
        if status is None:
            raise RuntimeError("Command status timed out")
        if status.stage not in (
            HandCommandStatus.STAGE_DISPATCHED,
            HandCommandStatus.STAGE_ACKNOWLEDGED,
        ):
            raise RuntimeError(f"Command failed: {status.error_code}")
        print("Protocol stage:", status.stage)
    finally:
        executor.shutdown()
        worker.join()
        hand.destroy()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
```

节点在独立线程 spin，主线程才能同步等待。业务中复用一个 `HandCommandClient`；命令返回的 publication 仅表示本地发布，后续 status 才表示驱动与协议进度。

## ROS 回调中的等待

异步 ROS 回调使用 rclpy Future：

```python
async def send_target(self, target):
    if not await self.hand.wait_until_ready_async(2.0):
        return None
    publication = self.hand.set_percent_angles(target)
    return await self.hand.wait_for_terminal_status_async(
        publication.user_sequence, 1.0
    )
```

检查返回 stage，不能把“收到终态”当作成功。高频 timer 使用 `is_ready("angles")` 与 `get_status(sequence)` 实现非阻塞状态机；单线程回调内不调用同步等待或嵌套 spin。详见[客户端等待](client_waits.md)。

## 配置、管理与恢复

```bash
ros2 service list -t
ros2 service call /linkerbot_hand/get_configured_speeds \
  linkerbot_hand_msgs/srv/GetRawValues '{timeout_s: 0.5}'
ros2 service call /linkerbot_hand/recover \
  linkerbot_hand_msgs/srv/Recover '{timeout_s: 1.0}'
```

配置回读可能是主动查询、设备回复缓存或本地命令缓存，检查 `state.meta`、单位和[读取模式](models.md#配置读取的三种结果)。服务只在能力支持时暴露。

恢复前停止目标生产，恢复后等待新代次的有效状态并显式发送新目标，不重放旧目标。协议下发或 ACK 均不等于机械到位；到位容差与稳定时间由[业务节点](business_integration.md)判断。

随包工具还有 `state_monitor`（读状态）、`angle_controller`（持续控制）和 [frequency_benchmark](frequency_benchmark.md)；运行各工具的 `--help` 查看参数。

[返回总览](getting_started.md) · [English](../examples.md)
