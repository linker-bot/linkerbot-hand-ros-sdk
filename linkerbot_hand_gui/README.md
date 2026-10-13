# O6 图形界面

[ROS 使用手册](../linkerbot_hand_ros/README_zh.md) · [安装与构建](../linkerbot_hand_ros/docs/zh/getting_started.md)

通过 URDF 滑块预览 O6，并通过 ROS bridge 控制实机。GUI 不打开 CAN 或创建 `HandDevice`，
设备 I/O 由驱动负责；支持左右 O6，不提供其他型号或指尖拖动/IK。

## 准备模型资源

URDF、decoder 和 mesh 来自 [linker-sim-assets](https://github.com/linker-bot/linker-sim-assets)。
安装 Git LFS 并取得完整资源：

```bash
sudo apt install -y git-lfs
git lfs install
git clone https://github.com/linker-bot/linker-sim-assets.git ~/linker-sim-assets
git -C ~/linker-sim-assets lfs pull
export LINKERBOT_HAND_ASSETS_ROOT=~/linker-sim-assets/src/linker_robot_assets/assets
```

也可安装包含资源的 `linker_robot_assets` 包，让启动器调用其 `asset_root()`；
显式 `assets_root` 优先。GUI 不复制模型资源；预览和实机模式均优先使用完整 visual GLB，
缺失或下载不完整时依次尝试同名 OBJ、对应碰撞 OBJ。回退模型的材质或几何可能不完整，
完整外观仍需下载 Git LFS 资源。
O6 右手拇指 GLB 的缺失颜色槽会在用户缓存副本中补齐，不修改资源仓库。

## 仅预览

每个终端先[加载环境](../linkerbot_hand_ros/docs/zh/getting_started.md#4-每个终端加载环境)。
`preview_only:=true` 只启动 URDF、独立滑块窗口和 RViz，无需设备，也不加载 SDK 或创建 bridge：

```bash
ros2 launch linkerbot_hand_gui hand_gui.launch.py \
  side:=right \
  assets_root:="$HOME/linker-sim-assets/src/linker_robot_assets/assets" \
  preview_only:=true
```

此模式输出 `/linkerbot_hand_gui/preview_joint_states`，没有命令发布器或控制启用服务。

## 连接实机

终端一启动 O6 驱动，型号、侧别和通道必须匹配设备：

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=o6 side:=right \
  transport_json:='{"backend":"socketcan","channel":"can1"}'
```

终端二启动 GUI：

```bash
ros2 launch linkerbot_hand_gui hand_gui.launch.py \
  side:=right \
  assets_root:="$HOME/linker-sim-assets/src/linker_robot_assets/assets" \
  driver_name:=/linkerbot_hand
```

普通模式创建 bridge，但控制默认关闭；滑块只更新目标模型，实际模型显示角度反馈。
确认空间、O6 身份/侧别、active 状态和新鲜角度后，在第三个终端启用控制：

```bash
ros2 service call /o6_gui_bridge/set_control_enabled std_srvs/srv/SetBool '{data: true}'
```

**启用后再次移动滑块才产生实机目标。** 接受的新目标按 `command_rate_hz` 持续发送，
仅保留最新目标。第一条滑块消息建立基线；时间戳、数组重排、非控制关节变化和限位外等效值
不算新的控制目标。静止广播仍更新预览。

停止控制：

```bash
ros2 service call /o6_gui_bridge/set_control_enabled std_srvs/srv/SetBool '{data: false}'
```

停用会清除发送目标，重新启用后须再次移动滑块。驱动失活、就绪证据过期、角度无效、
超过 2 秒无反馈或连接代次变化都会解除发送资格；异常期间编辑只更新预览，恢复后不补发。
驱动就绪检查与[客户端](../linkerbot_hand_ros/docs/zh/client_waits.md)一致。
关闭 GUI 后按[驱动关闭流程](../linkerbot_hand_ros/docs/zh/configuration.md#lifecycle-行为)释放设备。

## 话题与显示语义

| 话题 | 用途 |
| --- | --- |
| `/linkerbot_hand_gui/raw_target_joint_states` | 滑块原始 URDF 弧度 |
| `/linkerbot_hand_gui/target_joint_states` | 目标模型 TF |
| `/linkerbot_hand_gui/actual_joint_states` | 反馈模型 TF |
| `<driver>/capabilities`、`<driver>/state/angles` | 校验能力及实际 percent 状态 |
| `<driver>/command/angles` | 显式启用且就绪、反馈有效时发布 percent 目标 |

Bridge 核对 O6、左右手和六个关节名称/顺序。URDF 限位用于显示和 percent 映射，
真实命令范围仍以 capability 为准。没有 `physical_rad` 时，模型姿态是 percent 到 URDF
限位的几何映射，不代表实测物理弧度。

## 显示排障

空白 RViz 先检查 mesh 错误并执行 `git -C ~/linker-sim-assets lfs pull`。
若模型缺少材质或仅显示碰撞几何，检查是否因 GLB 不完整而回退到 OBJ。
滑块是独立的 `Joint State Publisher` 窗口，
不在 RViz 面板内；找不到时检查其他屏幕。启动器已使用 Qt XCB 后端。
