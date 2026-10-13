#!/usr/bin/env python3
"""PC：实验配置入口；复用已验收后端，不自动下载或改变飞行配置。"""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROFILES = Path(__file__).resolve().parent / "profiles"
ACTIONS = ("prepare", "build", "up", "inspect", "scan",
           "verify", "fault", "contact-check", "view", "view-close", "down")


def load_profile(name):
    # 只接收清单中的名称，避免误读其他路径。
    paths = {p.stem: p for p in PROFILES.glob("*.json")}
    if name not in paths:
        raise ValueError(f"未知实验 {name}；先执行 list")
    profile = json.loads(paths[name].read_text())
    if profile["backend"] != "stage3-super" or profile["target"] != "docker":
        raise ValueError("当前入口只支持 stage3-super 的 Docker 后端")
    if profile["id"] != name:
        raise ValueError("实验名称与配置 id 不一致")
    return profile


def command_for(profile, action, case=None, build_jobs=None, humble_image=None):
    command = [sys.executable, str(ROOT / "stage3/super/super_docker.py"), action]
    if action == "up":
        command.extend(profile["up_args"])
    if action == "fault":
        if case is None:
            raise ValueError("fault 需要 --case lidar、planner 或 clock")
        command.extend(["--case", case])
    if build_jobs is not None:
        if action != "build" or build_jobs < 1:
            raise ValueError("--build-jobs 只用于 build，且必须大于 0")
        command.extend(["--build-jobs", str(build_jobs)])
    if humble_image is not None:
        if action != "build":
            raise ValueError("--humble-image 只用于 build")
        command.extend(["--humble-image", humble_image])
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "plan", *ACTIONS))
    parser.add_argument("--profile", default="super-gnss-corridor")
    parser.add_argument("--case", choices=("lidar", "planner", "clock"))
    parser.add_argument("--dry-run", action="store_true", help="只打印命令，不访问 Docker")
    parser.add_argument("--build-jobs", type=int, help="编译并发数，内存紧张时设为 1")
    parser.add_argument("--humble-image", help="显式覆盖固定基础镜像")
    args = parser.parse_args()
    try:
        if args.action == "list":
            for path in sorted(PROFILES.glob("*.json")):
                profile = load_profile(path.stem)
                print(f'{profile["id"]}: {profile["description"]}')
            return 0
        profile = load_profile(args.profile)
        if args.action == "plan":
            print(json.dumps(profile, ensure_ascii=False, indent=2))
            return 0
        command = command_for(profile, args.action, args.case, args.build_jobs, args.humble_image)
        print(shlex.join(command), flush=True)
        if args.dry_run:
            return 0
        # inspect/verify/fault 读取后端容器的实际配置；profile 只决定 up。
        return subprocess.run(command, cwd=ROOT, check=False).returncode
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
