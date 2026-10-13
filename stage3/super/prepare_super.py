#!/usr/bin/env python3
"""PC：初始化并检查课程 SUPER submodule，不复制或修改算法源码。"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "submodules/SUPER"
WORKSPACE_SOURCE = ROOT / "thirdparty/super_gazebo_ws/src"
PACKAGES = ("super_planner", "rog_map", "mars_uav_sim/mars_quadrotor_msgs")


def main():
    if not (SOURCE / ".git").exists():
        subprocess.run(["git", "submodule", "update", "--init", "submodules/SUPER"],
                       cwd=ROOT, check=True)
    for package in PACKAGES:
        for name in ("CMakeLists.txt", "package.xml"):
            if not (SOURCE / package / name).is_file():
                raise SystemExit(f"SUPER 核心文件缺失：{package}/{name}")
    if WORKSPACE_SOURCE.is_symlink():
        if WORKSPACE_SOURCE.resolve() != SOURCE.resolve():
            raise SystemExit(f"工作区链接指向其他源码，请先检查：{WORKSPACE_SOURCE}")
    elif WORKSPACE_SOURCE.exists():
        raise SystemExit(f"工作区存在旧源码，请先备份再 prepare：{WORKSPACE_SOURCE}")
    else:
        WORKSPACE_SOURCE.parent.mkdir(parents=True, exist_ok=True)
        WORKSPACE_SOURCE.symlink_to("../../submodules/SUPER", target_is_directory=True)
    revision = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                                       text=True).strip()
    print(f"SUPER 源码：{SOURCE}\ncommit：{revision}\n准备完成；下一步 build")


if __name__ == "__main__":
    main()
