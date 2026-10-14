# 快速开始

## 1. 选择 ROS 发行版并准备环境

按操作系统选择一项；同一份最新 `main` 源码支持这两种发行版：

- Ubuntu 22.04 / Python 3.10：使用 **ROS 2 Humble**，按 [Humble 安装指南](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html)配置 apt 软件源，然后执行 `export LINKERBOT_ROS_DISTRO=humble`。
- Ubuntu 24.04 / Python 3.12：使用 **ROS 2 Jazzy**，按 [Jazzy 安装指南](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)配置 apt 软件源，然后执行 `export LINKERBOT_ROS_DISTRO=jazzy`。

新部署使用与系统匹配的发行版；不要跨 Ubuntu 版本安装 ROS 二进制包。
使用系统 Python，虚拟环境通过 `--system-site-packages` 读取同一发行版的 ROS 包。
以下命令复用上方选择；每个发行版使用独立 venv 和工作空间。

```bash
sudo apt update
sudo apt install -y git can-utils python3-venv python3-rosdep \
  python3-colcon-common-extensions python3-setuptools python3-wheel \
  "ros-${LINKERBOT_ROS_DISTRO}-ros-base"
if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
  sudo rosdep init
fi
rosdep update --rosdistro "${LINKERBOT_ROS_DISTRO}"
source "/opt/ros/${LINKERBOT_ROS_DISTRO}/setup.bash"
/usr/bin/python3 -m venv --system-site-packages "$HOME/venvs/linkerbot-hand-${ROS_DISTRO}"
source "$HOME/venvs/linkerbot-hand-${ROS_DISTRO}/bin/activate"
python -m pip install --upgrade pip
```

colcon 复用 Ubuntu 提供的 setuptools/wheel，不要用 pip 升级这个构建环境中的 setuptools。

## 2. 安装最新 main 源码

克隆需要 Gitea 访问权限。先安装 Transport 和 Hand Python，再一起构建 ROS 消息包、驱动和 GUI。
已有源码目录请按[更新指南](update.md)操作。

```bash
mkdir -p ~/linkerbot_deps
cd ~/linkerbot_deps
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/linker-bot/linkerbot-transport.git linkerbot-transport
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python.git linkerbot-hand
python -m pip install -e './linkerbot-transport[all]' -e ./linkerbot-hand

mkdir -p "$HOME/linkerbot_${ROS_DISTRO}_ws/src"
cd "$HOME/linkerbot_${ROS_DISTRO}_ws/src"
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/linker-bot/linkerbot-hand-ros2.git linkerbot-hand-ros
```

本地 `linkerbot-hand` 目录对应 `linkerbot-hand-python` 仓库，Python 包名仍为 `linkerbot-hand`。

## 3. 构建并验证

在已加载 ROS 和 venv 的终端构建。rosdep 根据三个包的声明安装系统依赖，
包括 GUI 使用的 RViz、Joint State Publisher GUI 和 Robot State Publisher。
URDF 和 mesh 不由 rosdep 安装，按下方 GUI 资源步骤单独准备。

```bash
cd "$HOME/linkerbot_${ROS_DISTRO}_ws"
rosdep install --from-paths src --ignore-src -y --rosdistro "${ROS_DISTRO}"
rosdep check --from-paths src --ignore-src --rosdistro "${ROS_DISTRO}"
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source "$HOME/linkerbot_${ROS_DISTRO}_ws/install/setup.bash"
python -c 'import linkerbot_transport, linkerbot_hand; print("Python dependencies: OK")'
ros2 pkg prefix linkerbot_hand_msgs
ros2 pkg prefix linkerbot_hand_ros
ros2 pkg prefix linkerbot_hand_gui
ros2 pkg executables linkerbot_hand_gui
ros2 interface show linkerbot_hand_msgs/msg/HandJointCommand
```

确认 rosdep 检查成功，三个 `ros2 pkg prefix` 均指向当前工作空间；GUI 可执行文件列表
应包含 `linkerbot_hand_gui o6_gui_bridge`，消息定义应正常显示。以上检查不连接设备或打开图形窗口。
rosdep 的实际错误必须处理，单独的 `pkg_resources` 弃用警告不代表失败。
构建命令显式指定当前 Python，避免 CMake 选择与 ROS ABI 不匹配的解释器。

## 4. 每个终端加载环境

每个新终端先执行所选发行版的 `export LINKERBOT_ROS_DISTRO=humble` 或
`export LINKERBOT_ROS_DISTRO=jazzy`，再加载以下环境。一个终端只加载一个 ROS 发行版。

```bash
source "/opt/ros/${LINKERBOT_ROS_DISTRO}/setup.bash"
source "$HOME/venvs/linkerbot-hand-${ROS_DISTRO}/bin/activate"
source "$HOME/linkerbot_${ROS_DISTRO}_ws/install/setup.bash"
```

需要 O6 可视化时，另按 [O6 图形界面](gui.md)准备模型资源；命令行使用无需下载资源。

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
ros2 topic echo --once --qos-durability transient_local /linkerbot_hand/capabilities
ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/angles
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
接下来查看[型号功能](models.md)、[控制示例](examples.md)或 [O6 图形界面](gui.md)。

[返回总览](getting_started.md) · [English](../quick_start.md)
