#!/usr/bin/env python3
"""容器内离线自检：依赖、PX4 消息类型支持、Agent 动态库；不发飞行消息。"""
import importlib
import json
from pathlib import Path
import shutil
import subprocess

from ament_index_python.packages import get_package_prefix
from rclpy.serialization import deserialize_message, serialize_message
from px4_msgs.msg import (FailsafeFlags, OffboardControlMode, TrajectorySetpoint,
                          VehicleCommand, VehicleOdometry, VehicleStatus)


def main():
    report = {"scope": "离线依赖与消息自检，不证明双容器通信或飞行通过", "checks": []}

    def check(name, operation):
        try:
            detail = operation()
            report["checks"].append({"id": name, "passed": True, "detail": detail})
        except Exception as exc:
            report["checks"].append({"id": name, "passed": False, "detail": str(exc)})

    for package in ("px4_msgs", "ros_gz_bridge", "pcl_ros", "tf2_ros", "rmw_fastrtps_cpp"):
        check(package, lambda p=package: get_package_prefix(p))
    for module in ("numpy", "scipy", "yaml"):
        check(module, lambda m=module: str(importlib.import_module(m).__file__))

    def messages():
        for cls in (FailsafeFlags, OffboardControlMode, TrajectorySetpoint,
                    VehicleCommand, VehicleOdometry, VehicleStatus):
            original = cls()
            if deserialize_message(serialize_message(original), cls) != original:
                raise RuntimeError(f"{cls.__name__} CDR 往返失败")
        if VehicleStatus.MESSAGE_VERSION != 4:
            raise RuntimeError("当前控制桥要求 VehicleStatus v4")
        return "六种 PX4 消息 CDR 往返通过；VehicleStatus v4"

    check("px4-type-support", messages)

    def agent():
        path = shutil.which("MicroXRCEAgent")
        if path is None:
            raise RuntimeError("Agent 不在 PATH")
        result = subprocess.run(["ldd", path], capture_output=True, text=True, check=True)
        if "not found" in result.stdout:
            raise RuntimeError(result.stdout)
        return path

    check("agent-libraries", agent)
    check("source-record", lambda: Path("/opt/uav/sources.txt").read_text())
    report["passed"] = all(item["passed"] for item in report["checks"])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
