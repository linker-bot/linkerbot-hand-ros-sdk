# main 源码检查

日常安装使用 Transport、Hand SDK 和 ROS 仓库的最新 `main` 分支，步骤见
[安装说明](../README_zh.md)。Python 包元数据保留 Hand SDK 依赖名称，不固定其版本；
请先按文档安装两个依赖仓库的源码，再用 colcon 构建 ROS package。

变更记录通过 Git 历史及对应 PR 查看。

## 本地检查

需要先配置 ROS 2 Jazzy、安装最新依赖源码并构建消息，然后运行：

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
ruff check .
ruff format --check .
```
