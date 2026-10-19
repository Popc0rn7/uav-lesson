# PC 板端主机工作区

项目中出现 `.board-work` 时，先区分可复用的环境准备和单次实验内容。skill 维护流程及脚本，不收纳 SDK、venv、板端依赖归档、编译产物和日志；这些仍属于本机缓存，不进入 Git。

## 路径契约

项目根 `.env` 配置：

- `OHOS_SDK`：已解压 Native SDK 根，包含 build/cmake/ohos.toolchain.cmake。
- `OHOS_TOOLCHAINS_DIR`：SDK 配套的 toolchains 根，包含 hdc；它与 Native SDK 是两个目录。
- `OHOS_HOST_PYTHON`：主机 ROS 生成工具所在 venv 的解释器，保留 venv 路径，不 resolve 到基础 Python。
- `BOARD_WORK_DIR`：当前项目的主机工作区，建议 `.board-work`，忽略 Git。

环境变量优先于 `.env`；相对路径以显式项目根为基准，不绑定 GCOPTER 等相邻项目。新环境由用户提供已准备的 SDK/venv，缺失时报告，不自动联网安装或替换。

## 只读核验与记录

在 PC 项目根执行，替换脚本位置为所用 skill 的实际路径：

```sh
python3 skills/oh-ros2/scripts/board_workspace.py --project .
# 明确需要保留本机环境身份时：
python3 skills/oh-ros2/scripts/board_workspace.py --project . --write
```

脚本核验 SDK 元数据、toolchains/hdc、主机 Python，并 import em、catkin_pkg、lark、numpy、yaml。成功返回 SDK 身份、主机版本及明确路径；`--write` 仅写当前 BOARD_WORK_DIR/host-environment.json，不访问设备或安装包。输出不包含 API key。

主机环境需与目标 ROS 的 Python 生成工具版本匹配。已有工作环境的历史锁定参考为 Python 3.12.11、empy 3.3.4、catkin-pkg 1.0.0、lark 1.1.9、NumPy 2.2.6、PyYAML 6.0.2；这是已用环境记录，不强制所有项目照搬。构建前仍按当前依赖预检。

板端头文件/库快照必须与本次设备 ABI 关联；快照导出、重定位与应用 overlay 属于项目的构建/部署入口，不把其他工程 `.board-work` 整体作为依赖搬入。现有 venv 可通过 `.env` 显式复用；以后迁移时重新建立 venv，不直接移动带绝对 shebang 的目录。
