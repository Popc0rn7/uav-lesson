#!/usr/bin/env python3
"""PC：只读检查 Stage 3 Docker 基线，不拉取镜像或启动容器。"""
import argparse
import json
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ros-image", default="osrf/ros:humble-desktop-jammy")
    parser.add_argument("--sitl-container", default="uav-stage2-sitl")
    args = parser.parse_args()
    report = {"checks": [], "action": "stop"}

    def check(name, command, validate=None):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            ok = result.returncode == 0
            detail = (result.stdout + result.stderr).strip()
            if ok and validate:
                ok = validate(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            ok, detail = False, str(exc)
        report["checks"].append({"id": name, "passed": ok, "detail": detail})
        return ok

    if not shutil.which("docker"):
        report["checks"].append({"id": "docker-cli", "passed": False,
                                 "detail": "未找到 docker；需教师提供已有 Docker 环境"})
    elif check("docker-access", ["docker", "info", "--format", "{{.ServerVersion}}"]):
        check("ros-image", ["docker", "image", "inspect", args.ros_image,
                            "--format", "{{.Id}} {{.Os}}/{{.Architecture}} {{json .RepoDigests}}"])
        check("sitl-running", ["docker", "inspect", args.sitl_container,
                               "--format", "{{.State.Running}}"],
              lambda output: output.strip() == "true")
    passed = bool(report["checks"]) and all(c["passed"] for c in report["checks"])
    report["action"] = "baseline-visible" if passed else "stop"
    report["scope"] = "仅检查 Docker 访问、已有 ROS 镜像和 SITL 状态；不证明算法依赖或飞行通过"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
