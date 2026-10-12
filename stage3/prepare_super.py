#!/usr/bin/env python3
"""PC：复制本地 SUPER，保留已有 ROS 2 修改，仅转换 ROS 1 配置。"""
import argparse
from pathlib import Path
import shutil
import tempfile


PACKAGES = (
    "super_planner", "rog_map", "mars_uav_sim/mars_quadrotor_msgs",
    "mars_uav_sim/marsim_render", "mars_uav_sim/perfect_drone_sim", "mission_planner",
)


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "thirdparty/SUPER")
    parser.add_argument("--destination", type=Path,
                        default=root / "thirdparty/super_humble_ws/src/SUPER")
    parser.add_argument("--gazebo", action="store_true", help="保留 Gazebo 仿真时钟并支持绝对配置路径")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    destination = args.destination.absolute()
    if destination.exists() or destination.is_symlink():
        parser.error(f"目标已存在，请复用或选择新目录，不自动覆盖：{destination}")
    if destination.resolve().is_relative_to(source):
        parser.error("目标不能位于源目录内")
    convert = []
    for package in PACKAGES:
        cmake = source / package / "CMakeLists.txt"
        if cmake.is_file() and "find_package(ament_cmake" in cmake.read_text():
            continue
        convert.append(package)
        for filename in ("ros2.CMakeLists.txt", "ros2.package.xml"):
            template = source / package / "ros" / filename
            if not template.is_file():
                parser.error(f"缺少 ROS 2 模板：{template}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".super-prepare-", dir=destination.parent) as temp:
        snapshot = Path(temp) / "SUPER"
        shutil.copytree(source, snapshot, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "build", "install", "log",
                                                      ".worktrees", "__pycache__", "*.pyc",
                                                      "*.log"))
        for package in convert:
            directory = snapshot / package
            shutil.copy2(directory / "ros/ros2.CMakeLists.txt", directory / "CMakeLists.txt")
            shutil.copy2(directory / "ros/ros2.package.xml", directory / "package.xml")
        if args.gazebo:
            from patch_super_height import patch
            patch(snapshot)
            entry = snapshot / "super_planner/Apps/fsm_node_ros2.cpp"
            content = entry.read_text()
            begin = content.index('    // 检查是否使用仿真时间')
            end = content.index('    // 初始化FSM', begin)
            content = content[:begin] + content[end:]
            content = content.replace('cfg_path = CONFIG_FILE_DIR(cfg_path);',
                                      "if (cfg_path.empty() || cfg_path.front() != '/') cfg_path = CONFIG_FILE_DIR(cfg_path);")
            entry.write_text(content)
        snapshot.rename(destination)
    print(f"ROS 2 源码副本：{destination}")
    print(f"原始源码保留：{source}")
    print(f"已保留 ROS 2 配置：{len(PACKAGES) - len(convert)} 个包；转换：{len(convert)} 个包")
    print("目标发行版：Humble；原脚本的发行版路径未改写，未验证 Humble 兼容性。")
    print("符号链接原样保留；未安装依赖、构建或启动节点。")


if __name__ == "__main__":
    main()
