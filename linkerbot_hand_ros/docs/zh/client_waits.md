# 客户端等待

客户端等待用于确认指定驱动就绪和观察协议命令结果；所属节点必须持续 spin。

## 就绪条件

就绪要求已验证的 capability、指定驱动 `get_state` 返回 active 的新鲜响应，
以及 ROS 图中属于该驱动的命令订阅。录包或其他观察者订阅命令 Topic 不会让客户端就绪。
查询每 0.2 秒刷新，从请求发出起最多有效 1 秒；生命周期切换使未完成查询失效，迟到响应
不能延长证据寿命。这是 ROS 图身份核对，不是节点认证，也不代表设备健康或机械安全。
驱动收到每条命令时仍会检查 Lifecycle 和设备状态。

`HandCommandClient` 用独立 callback group 处理元数据、状态和等待超时；所属 Node 必须 spin。

## 按调用位置选择

| 调用位置 | 等待方式 |
| --- | --- |
| ROS 异步回调，包括单线程 executor | `await wait_until_ready_async(...)`、`await wait_for_terminal_status_async(...)` |
| ROS 同步回调 | 优先状态机或 Future 完成回调；阻塞等待要求多线程 executor 至少有一个空闲线程 |
| executor 外的业务线程 | 另一线程持续 spin 时可同步等待 |

异步方法返回 **rclpy Future**，用于 ROS executor 协程或 `add_done_callback`，
不能直接交给独立运行的 asyncio loop。回调内不要调用 `spin_until_future_complete`
或嵌套 spin；单线程同步等待会阻止消息处理，多线程全部被占用时同样如此。

## 异步等待示例

```python
async def send_target(self, target):
    if not await self.hand.wait_until_ready_async(2.0):
        return
    publication = self.hand.set_percent_angles(target)
    status = await self.hand.wait_for_terminal_status_async(
        publication.user_sequence, 1.0
    )
    if status is None:
        self.get_logger().warning("No terminal status before timeout")
```

高频控制用 `is_ready`、发布和后续 tick 的 `get_status`，不要逐次阻塞。
异步等待释放 executor 线程，但仍占用该互斥 callback group；客户端接收逻辑使用独立组。

## 超时与销毁

超时按经过的实际时间计算，不受暂停的 ROS 仿真时间影响。取消 Future 只取消等待，
超时或取消都不会撤回已发布命令。先销毁客户端再销毁 Node，未完成等待会以 `RuntimeError` 失败。
协议终态不代表机械到位；示例中的 `status` 还需检查失败/覆盖等 stage。

[返回总览](getting_started.md) · [English](../client_waits.md)
