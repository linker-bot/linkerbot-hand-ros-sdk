# 本地开发检查

先按[安装](../linkerbot_hand_ros/docs/zh/getting_started.md)或[更新](../linkerbot_hand_ros/docs/zh/update.md)
准备 Transport、Hand Python 和 ROS 的最新 `main`，构建消息包及所有消费者。
依赖源码更新后重新构建，不从另一 Python 环境借用已生成的 ROSIDL 类型。

在仓库根目录运行：

```bash
source /opt/ros/jazzy/setup.bash
source ~/venvs/linkerbot-hand-ros/bin/activate
source ~/linkerbot_ws/install/setup.bash
cd ~/linkerbot_ws/src/linkerbot-hand-ros
python -m pip install pytest ruff
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
ruff check .
ruff format --check .
```

测试使用替身/内存协议验证软件行为；适配器通信、真实受压响应和机械动作需要对应硬件验证。
命令发送、完整触觉与 ROS 发布频率的测试方法见[频率测试](../linkerbot_hand_ros/docs/zh/frequency_benchmark.md)。
变更记录通过 Git 历史及对应 PR 查看。
