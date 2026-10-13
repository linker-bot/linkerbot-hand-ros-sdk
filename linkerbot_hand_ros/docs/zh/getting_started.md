# 快速入门

## 1. 环境

本文只适用于 Ubuntu 24.04、ROS 2 Jazzy 和 Hand SDK 最新 `main`。完整依赖链为
`linkerbot-transport -> linkerbot-hand -> linkerbot_hand_msgs/linkerbot_hand_ros`。
安装系统工具并创建可以读取 ROS 系统包的隔离环境：

```bash
sudo apt update
sudo apt install -y git can-utils python3-venv python3-rosdep \
  python3-colcon-common-extensions

source /opt/ros/jazzy/setup.bash
/usr/bin/python3 -m venv --system-site-packages ~/venvs/linkerbot-hand-ros
source ~/venvs/linkerbot-hand-ros/bin/activate
```

从最新 `main` 分支安装 Transport 和 Hand：

```bash
mkdir -p ~/linkerbot_deps
cd ~/linkerbot_deps
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-transport.git linkerbot-transport
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-hand.git linkerbot-hand
python -m pip install -e './linkerbot-transport[all]' -e ./linkerbot-hand
```

已有源码目录时，先同步两个仓库的 `main`，再重新安装：

```bash
git -C ~/linkerbot_deps/linkerbot-transport switch main
git -C ~/linkerbot_deps/linkerbot-transport pull --ff-only origin main
git -C ~/linkerbot_deps/linkerbot-hand switch main
git -C ~/linkerbot_deps/linkerbot-hand pull --ff-only origin main
python -m pip install -e "$HOME/linkerbot_deps/linkerbot-transport[all]" \
  -e "$HOME/linkerbot_deps/linkerbot-hand"
```

## 2. CAN 接口

经典 CAN 示例：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
ip -details -statistics link show can0
```

CAN FD 示例：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000 dbitrate 5000000 fd on
sudo ip link set can0 up
ip -details -statistics link show can0
```

实际 nominal/data bitrate 必须与设备 capability 和硬件手册一致。不要在驱动运行时再启动
另一个会主动查询设备的测试程序；`candump` 只监听，可用于检查总线。

## 3. 构建 ROS 工作空间

`linkerbot_hand_msgs` 是需要由 Jazzy 生成的 ROSIDL package，不包含在驱动 Python
wheel 中。必须从同一个最新 `main` 源码目录构建消息和驱动：

```bash
mkdir -p ~/linkerbot_ws/src
cd ~/linkerbot_ws/src
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-hand-ros2.git linkerbot-hand-ros
cd ~/linkerbot_ws
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source ~/linkerbot_ws/install/setup.bash

python -c 'import linkerbot_transport, linkerbot_hand; print("Python dependencies: OK")'
ros2 pkg prefix linkerbot_hand_msgs
ros2 pkg prefix linkerbot_hand_ros
ros2 interface show linkerbot_hand_msgs/msg/HandJointCommand >/dev/null
ros2 pkg executables linkerbot_hand_ros
```

已有 ROS 工作空间时，在更新 SDK 源码后同步 ROS 的 `main`，并重建所有包和下游消费者：

```bash
git -C ~/linkerbot_ws/src/linkerbot-hand-ros switch main
git -C ~/linkerbot_ws/src/linkerbot-hand-ros pull --ff-only origin main
cd ~/linkerbot_ws
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source ~/linkerbot_ws/install/setup.bash
```

rosdep 的弃用警告可以记录后继续，unresolved key 或 `ERROR:` 必须处理。
以上验证不连接设备，也不会发送 CAN 帧。

## 4. 启动与检查

L6 左手：

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l6 side:=left \
  transport_json:='{"backend":"socketcan","channel":"can0"}'
```

L30 不区分左右手：

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l30 side:='' \
  transport_json:='{"backend":"socketcan","channel":"can0"}'
```

L6/O6 等多手部署按一通道一只手接线，使用容器统一启停：

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py
```

默认读取随包安装的 `config/multi_hand.yaml`：L6 左手使用 `can0`，O6 右手使用
`can1`。启动前分别配置两个接口；其他接线使用自己的绝对路径：

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py \
  config:=/absolute/path/to/hands.yaml
```

参数文件中的 `device_namespaces` 决定内部 Lifecycle 节点。每个 namespace 必须有对应的
`/<namespace>/linkerbot_hand` 参数段。不同 channel 分别建立 runtime；SDK 对相同物理
key 的资源共享不代表支持同通道多手，namespace 也不提供设备报文隔离。
需要容器的组启动和失败回滚时使用该入口；独立 launch 进程不具备这些组生命周期能力。

确认 active、身份已验证且角度属于当前连接代次：

```bash
ros2 lifecycle get /linkerbot_hand
ros2 topic echo --once /linkerbot_hand/capabilities
ros2 topic echo --once /linkerbot_hand/device_info
ros2 topic echo --once /linkerbot_hand/state/angles
ros2 topic echo --once /diagnostics
```

`capabilities.identity.verified` 应为 `true`。`state/angles.meta` 应满足 `valid=true`、
`stale=false`，且 `connection_generation` 与 diagnostics 一致。

## 5. 无运动通信验证

先只观察状态，不发送目标：

```bash
ros2 topic hz /linkerbot_hand/state/angles
ros2 param set /linkerbot_hand angles_hz 60.0
ros2 param set /linkerbot_hand angles_hz 0.0
```

`angles_hz=0` 后 SDK 不再产生角度查询。恢复轮询：

```bash
ros2 param set /linkerbot_hand angles_hz 60.0
```

## 6. 首条命令

先从当前姿态附近的小范围目标开始。以下只展示消息格式，不代表任意设备都可安全直接运动：

```bash
ros2 topic pub --once /linkerbot_hand/command/angles \
  linkerbot_hand_msgs/msg/HandJointCommand \
  '{client_id: 1, user_sequence: 1, representation: 1, values: [50, 50, 50, 50, 50, 50]}'
ros2 topic echo /linkerbot_hand/command/status
```

`representation=1` 是 percent；`representation=2` 是协议 raw。关节数量和顺序只能从
capability 读取。收到 `DISPATCHED` 只证明 transport send 成功，机械到位仍需状态反馈判断。
`/command/status` 的类型是 `HandCommandStatusBatch`；其中每个 `statuses[]` 元素对应一条命令，
不能把整批消息当成单条状态。

下一步参阅[参数配置](configuration.md)、[ROS API](ros_api.md)和
[业务集成](business_integration.md)。
