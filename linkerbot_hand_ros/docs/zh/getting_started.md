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
  https://gitea.linkerhub.work/linker-bot/linkerbot-transport.git linkerbot-transport
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python.git linkerbot-hand
python -m pip install -e './linkerbot-transport[all]' -e ./linkerbot-hand

mkdir -p ~/linkerbot_ws/src
cd ~/linkerbot_ws/src
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/linker-bot/linkerbot-hand-ros2.git linkerbot-hand-ros
```

本地 `linkerbot-hand` 目录对应 `linkerbot-hand-python` 仓库，Python 包名仍为 `linkerbot-hand`。

## 3. 构建并验证

在已加载 ROS 和 venv 的终端构建。rosdep 根据三个包的声明安装系统依赖，
包括 GUI 使用的 RViz、Joint State Publisher GUI 和 Robot State Publisher。
URDF 和 mesh 不由 rosdep 安装，按下方 GUI 资源步骤单独准备。

```bash
cd ~/linkerbot_ws
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
rosdep check --from-paths src --ignore-src --rosdistro jazzy
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source ~/linkerbot_ws/install/setup.bash
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

```bash
source /opt/ros/jazzy/setup.bash
source ~/venvs/linkerbot-hand-ros/bin/activate
source ~/linkerbot_ws/install/setup.bash
```

### 可选：准备 O6 GUI 资源

需要 O6 可视化时，按 [GUI 资源准备](../../../linkerbot_hand_gui/README.md#准备模型资源)
安装 Git LFS 并下载 `linker-sim-assets`，再按[仅预览](../../../linkerbot_hand_gui/README.md#仅预览)
验证模型显示；预览需要桌面图形环境，无需连接设备。GUI 包构建成功不代表模型资源已下载。
驱动通信和命令行使用无需这些模型资源。

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
