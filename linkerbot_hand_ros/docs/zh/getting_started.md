# 安装与首组角度

[English](../getting_started.md) · [使用手册](../../README_zh.md)

## 1. 准备 ROS 和 Python

以下命令适用于 Ubuntu 24.04 / ROS 2 Jazzy。先按
[ROS 安装指南](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)配置 apt 软件源。
使用 Ubuntu 系统 Python，并通过 `--system-site-packages` 让虚拟环境能读取 ROS 系统包。

```bash
sudo apt update
sudo apt install -y git can-utils python3-venv python3-rosdep \
  python3-colcon-common-extensions python3-setuptools python3-wheel ros-jazzy-ros-base
if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
  sudo rosdep init
fi
rosdep update
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 -m venv --system-site-packages ~/venvs/linkerbot-hand-ros
source ~/venvs/linkerbot-hand-ros/bin/activate
python -m pip install --upgrade pip
```

colcon 使用 Ubuntu 提供的 setuptools/wheel；venv 通过 `--system-site-packages` 复用它们。

## 2. 安装最新 main 源码

克隆需要 Gitea 访问权限。先安装 Transport 和 Hand Python，再一起构建 ROS 消息包、驱动和 GUI。
已有源码目录请按[更新指南](update.md)操作。

```bash
mkdir -p ~/linkerbot_deps
cd ~/linkerbot_deps
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-transport.git linkerbot-transport
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python.git linkerbot-hand
python -m pip install -e './linkerbot-transport[all]' -e ./linkerbot-hand

mkdir -p ~/linkerbot_ws/src
cd ~/linkerbot_ws/src
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-hand-ros2.git linkerbot-hand-ros
```

本地 `linkerbot-hand` 目录对应 `linkerbot-hand-python` 仓库，Python 包名仍为 `linkerbot-hand`。

## 3. 构建并验证

```bash
cd ~/linkerbot_ws
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source ~/linkerbot_ws/install/setup.bash
python -c 'import linkerbot_transport, linkerbot_hand; print("Python dependencies: OK")'
ros2 pkg prefix linkerbot_hand_msgs
ros2 pkg prefix linkerbot_hand_ros
ros2 interface show linkerbot_hand_msgs/msg/HandJointCommand
```

应能导入依赖、找到 ROS package 并显示消息定义；这一步不连接设备。
rosdep 的实际错误必须处理，单独的 `pkg_resources` 弃用警告不代表失败。
构建命令显式指定当前 Python，避免 CMake 选择与 ROS ABI 不匹配的解释器。

## 4. 每个终端加载环境

```bash
source /opt/ros/jazzy/setup.bash
source ~/venvs/linkerbot-hand-ros/bin/activate
source ~/linkerbot_ws/install/setup.bash
```

## 5. 连接一只手

先[准备通信接口](connection.md)，给设备上电，在扫描范围内仅连接一只手，然后启动：

```bash
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true
```

限定接口可追加 `channels:=can0`。未找到、找到多个或身份不完整时会报错；
多手及厂商适配器见[自动发现](discovery.md)。发现和激活会读取身份与状态，不发送运动目标。

在另一个终端加载相同环境，读取：

```bash
ros2 lifecycle get /linkerbot_hand
ros2 topic echo --once /linkerbot_hand/capabilities
ros2 topic echo --once /linkerbot_hand/state/angles
```

应看到 `active`、`identity.verified=true`，以及角度 `meta.valid=true`、`stale=false`。
`joint_names` 给出数组顺序；raw、percent 和物理弧度分别有有效性标记。

## 6. 结束或继续

先停止业务节点发送目标，再释放驱动连接：

```bash
ros2 lifecycle set /linkerbot_hand deactivate
ros2 lifecycle set /linkerbot_hand cleanup
```

最后在 launch 终端按 Ctrl+C。deactivate 只停止命令与轮询，cleanup 才关闭连接。
接下来查看[型号功能](models.md)、[控制示例](examples.md)或 [O6 GUI](../../../linkerbot_hand_gui/README.md)。
