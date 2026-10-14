# L20Lite 功能文档

L20Lite 使用CAN，包含 10 个关节。以下示例使用 `/linkerbot_hand`；多手部署请替换为实际驱动路径。命令会移动设备，执行前核对当前状态、方向和目标。

## 连接设备

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l20lite side:=right \
  transport_json:='{"backend":"socketcan","channel":"can0"}'
```

[自动连接](discovery.md)无需手动填写型号。将 side 改为设备的实际 left 或 right。

## 关节顺序

数组顺序以当前 `capabilities.joints` 和状态的 `joint_names` 为准。此表供识别关节：

| 索引编号 | 关节名称 | 关节 |
| ---: | --- | --- |
| 1 | `thumb_flex` | 拇指弯曲 |
| 2 | `thumb_roll` | 拇指翻滚 |
| 3 | `index_flex` | 食指弯曲 |
| 4 | `middle_flex` | 中指弯曲 |
| 5 | `ring_flex` | 无名指弯曲 |
| 6 | `pinky_flex` | 小指弯曲 |
| 7 | `index_abd` | 食指侧摆 |
| 8 | `ring_abd` | 无名指侧摆 |
| 9 | `pinky_abd` | 小指侧摆 |
| 10 | `thumb_rotation` | 拇指旋转 |

## 身份与能力

```bash
ros2 topic echo --once --qos-durability transient_local /linkerbot_hand/capabilities
ros2 service call /linkerbot_hand/get_device_info \
  linkerbot_hand_msgs/srv/GetDeviceInfo '{timeout_s: 0.2}'
ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/angles
```

确认 `identity.verified=true`，再读取支持的命令、数值范围、触觉字段和配置读取模式。

## 角度控制

角度状态包含 `raw`、`percent` 及可选的 `physical_rad`；使用前检查 `meta.valid`、`meta.stale` 和各轴有效性。屈伸 percent 的 0 表示弯曲端，100 表示伸直端；侧摆等关节按能力中的端点解释。

```bash
ros2 run linkerbot_hand_ros angle_command --values 50 50 50 50 50 50 50 50 50 50
```

`angle_command` 默认使用 percent，加 `--raw` 使用协议原值。Python 客户端对应 `set_percent_angles(values)` 与 `set_angles(raw_values)`。协议完成不等于机械到位，见[控制示例](examples.md)。

## 速度设置

使用 `HandCommandClient.set_speeds(raw_values)` 或 `command/speeds`，数组数量与关节数一致。raw 是协议值；`configured_speeds` 是速度设置，`measured_speeds` 才是实时速度。当前配置回读见下方型号差异；未暴露 `get_configured_speeds` 的型号不支持该 ROS 回读服务。

```python
# hand 为运行中节点上的常驻 HandCommandClient。
publication = hand.set_speeds([100] * len(hand.joint_names))
```

```bash
ros2 service call /linkerbot_hand/get_configured_speeds \
  linkerbot_hand_msgs/srv/GetRawValues '{timeout_s: 0.5}'
```

## 加速度设置

使用 `HandCommandClient.set_accelerations(raw_values)` 或 `command/accelerations`，数值范围见 `capabilities.commands`。

## 状态与触觉读取

```bash
ros2 param set /linkerbot_hand current_hz 10.0
ros2 param set /linkerbot_hand temperature_hz 1.0
ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/currents
```

其他状态按支持情况启用，见[参数配置](configuration.md)。开启 fn 触觉后读取完整样本：

```bash
ros2 param set /linkerbot_hand force_fn_hz 10.0
ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/tactile
```

触觉点阵消息保留各指的行列布局，不能把点阵求和当作设备合力。字段、单位和有效性见[触觉数据](force.md)。

## 型号差异与管理

十关节角度、速度、加速度和电流限制设置。速度/加速度/电流限制读取使用设备写回包缓存；
实时速度与电流独立查询。堵转配置只提供写入和已确认写回包状态，没有 `get_stall_protection`。
不提供清错或掉电保存。

fn 为五指 12×6 点阵；fns、fts、fds、px 为独立查询的五指标量。
fns 由设备提供，不由点阵求和；fds 保留方向编码和有效性，不换算角度。

停止业务命令后执行[deactivate 与 cleanup](configuration.md#lifecycle-行为)关闭连接。

[返回总览](getting_started.md) · [English](../l20lite.md)
