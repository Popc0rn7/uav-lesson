"""PC：通过 AirSim 的 PX4 API 执行短距离往返，不使用 SUPER 规划器。"""
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import re
import time

from rpc_client import rpc
from runtime import px4

VEHICLE = "PX4"


def snapshot():
    state = rpc("getMultirotorState", VEHICLE, timeout=4)
    kinematics = state["kinematics_estimated"]
    return dict(timestamp=state["timestamp"], landed=state["landed_state"],
                position=[kinematics["position"][axis + "_val"] for axis in "xyz"],
                velocity=[kinematics["linear_velocity"][axis + "_val"] for axis in "xyz"])


class Flight:
    def __init__(self, state):
        self.state = state
        self.records = []
        self.pool = ThreadPoolExecutor(2)
        self.origin = snapshot()["position"]

    def sample(self, label):
        current = snapshot()
        if not all(math.isfinite(x) for x in current["position"] + current["velocity"]):
            raise RuntimeError("飞行状态包含非有限值")
        self.records.append(dict(label=label, wall_time=time.time(), **current))
        return current

    def action(self, method, *args, timeout):
        if method.startswith(("move", "rotate")):
            # hover 的模式切换会清除内部控制请求，不依赖 isApiControlEnabled。
            rpc("enableApiControl", True, VEHICLE)
        future = self.pool.submit(rpc, method, *args, timeout=timeout + 5)
        deadline = time.monotonic() + timeout
        fresh_at = time.monotonic()
        previous = None
        while not future.done():
            current = self.sample(method)
            if current["timestamp"] != previous:
                previous = current["timestamp"]
                fresh_at = time.monotonic()
            if time.monotonic() - fresh_at > 3:
                raise RuntimeError("PX4 状态停流")
            if method != "land":
                horizontal = math.dist(current["position"][:2], self.origin[:2])
                if horizontal > 5 or current["position"][2] < self.origin[2] - 6:
                    raise RuntimeError("超出本例的 5 m 水平 / 6 m 高度范围")
            if time.monotonic() > deadline:
                raise TimeoutError(f"{method} 超时")
            time.sleep(.25)
        result = future.result()
        self.records.append(dict(command=method, result=result, wall_time=time.time()))
        if result is False:
            raise RuntimeError(f"{method} 返回 false")
        return self.sample(method + "-end")

    def hold(self, label, seconds):
        self.action("hover", VEHICLE, timeout=10)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.sample(label)
            time.sleep(.25)
        return self.sample(label + "-end")

    def land(self):
        rpc("cancelLastTask", VEHICLE, timeout=3)
        current = self.sample("before-land")
        if current["landed"] != 0:
            self.action("land", 45, VEHICLE, timeout=50)
        current = self.sample("landed")
        if current["landed"] != 0:
            raise RuntimeError("未确认落地；不强制解除解锁")
        if not rpc("armDisarm", False, VEHICLE):
            raise RuntimeError("解除解锁被拒绝")
        rpc("enableApiControl", False, VEHICLE)
        result = px4(self.state, "commander", "mode", "auto:loiter")
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        if "arming_state: 1" not in px4(self.state, "listener", "vehicle_status").stdout:
            raise RuntimeError("PX4 未报告解除解锁")


def validate(config):
    for key in ["start_ned_m", "goal_ned_m"]:
        point = config[key]
        if (len(point) != 3 or not all(math.isfinite(x) for x in point)
                or math.hypot(*point[:2]) > 3 or not -5 <= point[2] <= -1):
            raise ValueError(f"{key} 需为 NED 米坐标，水平半径≤3 m，高度1～5 m")
    for key, low, high in [("speed_m_s", .1, 1), ("hover_s", 1, 10),
                           ("position_tolerance_m", .15, 1), ("leg_timeout_s", 5, 60)]:
        if not low <= config[key] <= high:
            raise ValueError(f"{key} 需在 {low}～{high} 范围内")
    if math.dist(config["start_ned_m"], config["goal_ned_m"]) < .8:
        raise ValueError("起点与终点至少间隔 0.8 m，避免 API 直接按到点阈值返回")


def land(state):
    flight = Flight(state)
    try:
        flight.land()
        print("已着陆、解除解锁并回到 Hold")
    finally:
        flight.pool.shutdown(wait=False)


def run_task(state):
    config = state["config"]["task"]
    validate(config)
    flight = Flight(state)
    original = {}
    owns_control = False
    error = None
    endpoints = []
    report = Path(state["run_dir"]) / f"task-{time.time_ns()}.json"
    try:
        initial = flight.sample("initial")
        if initial["landed"] != 0 or math.hypot(*initial["position"][:2]) > 1:
            raise RuntimeError("需要先落地并位于出生点附近 1 m 范围内")
        px4(state, "commander", "mode", "auto:loiter")
        if "Preflight check: OK" not in px4(state, "commander", "check").stdout:
            raise RuntimeError("起飞前健康检查不通过")
        for name in ["MPC_XY_VEL_MAX", "MPC_XY_CRUISE", "MPC_VEL_MANUAL"]:
            raw = px4(state, "param", "show", name)
            if raw.returncode:
                raise RuntimeError(raw.stderr)
            original[name] = float(re.search(r":\s*([-0-9.]+)", raw.stdout)[1])
        rpc("enableApiControl", True, VEHICLE)
        owns_control = True
        if not rpc("armDisarm", True, VEHICLE):
            raise RuntimeError("解锁被拒绝")
        print("起飞…", flush=True)
        flight.action("takeoff", 25, VEHICLE, timeout=30)
        for label, target in [("start", config["start_ned_m"]),
                              ("goal", config["goal_ned_m"]),
                              ("return", config["start_ned_m"])]:
            print(f"{label} → NED {target}，{config['speed_m_s']} m/s", flush=True)
            flight.action("moveToPosition", *target, config["speed_m_s"],
                          config["leg_timeout_s"], 0, {"is_rate": True, "yaw_or_rate": 0.},
                          -1., 1., VEHICLE, timeout=config["leg_timeout_s"] + 5)
            current = flight.hold(label + "-hover", config["hover_s"])
            distance = math.dist(current["position"], target)
            endpoints.append(dict(label=label, target=target, measured=current["position"], error_m=distance))
            print(f"{label} 悬停后误差 {distance:.3f} m", flush=True)
            if distance > config["position_tolerance_m"]:
                raise RuntimeError(f"{label} 到点误差超过容限")
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if owns_control:
            try:
                print("降落…", flush=True)
                flight.land()
            except Exception as exc:
                error = (error or "") + f" landing: {exc}"
        for name, value in original.items():
            try:
                result = px4(state, "param", "set", name, str(value))
                if result.returncode:
                    raise RuntimeError(result.stderr)
            except Exception as exc:
                error = (error or "") + f" parameter restore {name}: {exc}"
        report.write_text(json.dumps(dict(passed=error is None, error=error,
                                         task=config, original_parameters=original,
                                         endpoints=endpoints, records=flight.records), indent=2))
        flight.pool.shutdown(wait=False)
        print(f"任务结果：{report}", flush=True)
    if error:
        raise RuntimeError(error)
    print("往返任务通过，已降落并解除解锁")
