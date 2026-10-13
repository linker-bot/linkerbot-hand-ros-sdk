# Linkerbot Hand ROS 2

本仓库包含两个可由 ROS 2 独立发现的 package：

- [`linkerbot_hand_msgs`](./linkerbot_hand_msgs)：类型化消息和服务。
- [`linkerbot_hand_ros`](./linkerbot_hand_ros)：Lifecycle 驱动和配套工具。

## 快速启动

最新 `main` 的统一触觉字段及各型号能力见[触觉字段指南](linkerbot_hand_ros/docs/zh/force.md)。
电流限制使用 `current_limits`，O30 独立的转矩限制使用 `torques_limits`，详见
[电流与转矩接口](linkerbot_hand_ros/docs/zh/ros_api.md#按需读取配置与限制状态)。
下方命令从三个仓库的最新 `main` 分支安装。

完整依赖链为
`linkerbot-transport -> linkerbot-hand -> linkerbot_hand_msgs/linkerbot_hand_ros`。
Transport 和 Hand 从源码安装；ROS package 从同一个 `main` 源码目录通过 `colcon` 构建。
以下命令适用于已经配置 ROS 2 apt 软件源的 Ubuntu 24.04：

使用 Ubuntu 系统 Python 创建虚拟环境，以匹配 ROS 的 Python ABI；构建命令也显式指定
当前环境的解释器，避免 CMake 选到另装的 Python 版本。

```bash
sudo apt update
sudo apt install -y \
  git can-utils python3-venv python3-rosdep \
  python3-colcon-common-extensions ros-jazzy-ros-base

if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
  sudo rosdep init
fi
rosdep update

source /opt/ros/jazzy/setup.bash
/usr/bin/python3 -m venv --system-site-packages ~/venvs/linkerbot-hand-ros
source ~/venvs/linkerbot-hand-ros/bin/activate
python -m pip install --upgrade pip
mkdir -p ~/linkerbot_deps
cd ~/linkerbot_deps
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-transport.git linkerbot-transport
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-hand.git linkerbot-hand
python -m pip install -e './linkerbot-transport[all]' -e ./linkerbot-hand

mkdir -p ~/linkerbot_ws/src
cd ~/linkerbot_ws/src
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-hand-ros2.git linkerbot-hand-ros

cd ~/linkerbot_ws
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source ~/linkerbot_ws/install/setup.bash

python - <<'PY'
from importlib.metadata import version

import linkerbot_hand
import linkerbot_transport

print("linkerbot-transport", version("linkerbot-transport"))
print("linkerbot-hand", version("linkerbot-hand"))
print("python imports: OK")
PY
ros2 pkg prefix linkerbot_hand_msgs
ros2 pkg prefix linkerbot_hand_ros
ros2 interface show linkerbot_hand_msgs/msg/HandJointCommand >/dev/null
ros2 pkg executables linkerbot_hand_ros
```

验证应显示实际安装的 Transport 和 Hand 版本、两个 ROS package 的工作空间安装前缀，
以及 `hand_node` 等可执行程序。版本号仅用于诊断，依赖源码以最新 `main` 为准。
该步骤不连接设备，也不会发送 CAN 帧。每个新终端依次执行：

```bash
source /opt/ros/jazzy/setup.bash
source ~/venvs/linkerbot-hand-ros/bin/activate
source ~/linkerbot_ws/install/setup.bash
```

ROS 2 apt 软件源的首次配置见
[ROS 2 Jazzy 官方安装说明](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)。
实机 CAN 配置、启动参数和接口检查见下方驱动文档。

安装、运行和接口说明见[驱动中文文档](./linkerbot_hand_ros/README_zh.md)，英文说明见
[driver README](./linkerbot_hand_ros/README.md)。
