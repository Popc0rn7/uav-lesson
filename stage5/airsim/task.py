"""PC：AirSim task：健康检查 → 起飞/悬停确认 → 开车 → Qwen/Jev任务。"""
import argparse
import fcntl
import hashlib
import json
import math
from pathlib import Path
import queue
import signal
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT/'stage5'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import numpy as np

from dino_client import configuration
from latency import record as record_latency, summarize as summarize_latency
from evidence import write_json
from follow import Flight, rotation
from stage5.airsim.config import camera_model
from stage5.airsim.convoy_client import ConvoyClient
from stage5.airsim.preflight import check
from stage5.airsim.runtime import call, inspect, px4, management_lock, request_land


def measure_camera(config):
    """静止未解锁时测量固定安装外参；飞行中只用PX4估计，不取场景位姿。"""
    samples = []
    for _ in range(3):
        own = call(config, 'getMultirotorState', config['vehicle_name'])
        body_pose = call(config, 'simGetVehiclePose', config['vehicle_name'])
        camera = call(config, 'simGetCameraInfo', 'front_center', config['vehicle_name'], False)
        if own.get('landed_state') != 0:
            raise ValueError('相机外参测量要求落地静止')
        def vector(value):
            return np.array([value[k] for k in ('x_val', 'y_val', 'z_val')], dtype=float)
        def quat(value):
            q = np.array([value[k] for k in ('w_val', 'x_val', 'y_val', 'z_val')], dtype=float)
            if not np.isfinite(q).all() or not .99 < np.linalg.norm(q) < 1.01:
                raise ValueError('相机或机体四元数无效')
            return q
        if abs(camera['fov']-90) > .1:
            raise ValueError('相机实际FOV与当前标定不一致')
        body = own['kinematics_estimated']; pose = camera['pose']
        body_r, camera_r = rotation(quat(body_pose['orientation'])), rotation(quat(pose['orientation']))
        offset = body_r.T @ (vector(pose['position'])-vector(body_pose['position']))
        relative_r = body_r.T @ camera_r
        samples.append((offset, relative_r))
        if not np.isfinite(offset).all() or np.linalg.norm(offset) > 2 or not np.isfinite(relative_r).all():
            raise ValueError('相机与机体参考系不一致，不能推算安装外参')
        if np.linalg.norm(vector(body['linear_velocity'])) > .05:
            raise ValueError('外参测量时机体正在运动')
        # 当前前向技能/体素扫掠仅支持水平前向相机。
        if np.max(np.abs(relative_r-np.eye(3))) > .02:
            raise ValueError('当前任务要求水平前向相机，不自动忽略相机旋转')
    if any(np.linalg.norm(p-samples[0][0]) > .01 or np.max(np.abs(r-samples[0][1])) > .01 for p, r in samples):
        raise ValueError('相机安装测量不稳定')
    model = camera_model(config)
    model.update(position_body_frd_m=samples[0][0].tolist(), rotation_camera_frd_to_body_frd=samples[0][1].tolist(),
        body_center_camera_flu_m=((-samples[0][1].T@samples[0][0])*[1, -1, -1]).tolist(),
        extrinsics_source='three stationary AirSim body/camera relative-pose samples; no in-flight truth')
    return model


def await_hover(flight, initial, height, result, timeout, record, clock=time.monotonic, sleep=time.sleep, cancel=None):
    began = clock(); deadline = began+timeout; settled = None; holding = False; completed = False
    while clock() < deadline:
        if cancel: cancel()
        flight.poll(); now = clock(); own = flight.snapshot()
        if own is None or own['age'] > .5 or now-flight.heartbeat_at > 3:
            raise RuntimeError('起飞期间PX4遥测失流')
        if not flight.armed:
            if now-began < 3:
                sleep(.02); continue
            raise RuntimeError('起飞期间PX4未解锁或已解除解锁')
        try:
            ok, value = result.get_nowait()
            if not ok or value is not True:
                raise RuntimeError('AirSim/PX4起飞请求失败')
            completed = True
        except queue.Empty:
            pass
        height_ok = abs((initial[2]-own['p'][2])-height) <= .4
        if completed and height_ok and not holding:
            flight.hold(); holding = True; record('hold_requested')
        settled_ok = (height_ok and np.linalg.norm(own['v']) < .3 and completed
                      and flight.mode == 4 and flight.sub_mode == 3)
        settled = now if settled_ok and settled is None else settled if settled_ok else None
        if settled is not None and now-settled >= 2:
            record('takeoff_complete', position_ned_m=own['p'].tolist(), velocity_ned_mps=own['v'].tolist())
            return
        sleep(.02)
    raise TimeoutError('起飞/悬停屏障超时')


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'run'))
    parser.add_argument('--state-dir', type=Path, default=ROOT/'artifacts/stage5-airsim')
    parser.add_argument('--prompt-id', default='pickup_rear_follow')
    parser.add_argument('--takeoff-height', type=float, default=8., help='相对起飞点的PX4爬升高度，2～8米')
    parser.add_argument('--takeoff-timeout', type=float, default=60.)
    parser.add_argument('--budget', type=int, default=10)
    parser.add_argument('--timeout', type=float, default=180., help='悬停屏障之后模型任务的墙钟预算')
    args = parser.parse_args(argv)
    if (args.budget < 1 or not all(math.isfinite(v) and v > 0 for v in (args.takeoff_height, args.takeoff_timeout, args.timeout))
            or not 2 <= args.takeoff_height <= 8 or not 10 <= args.takeoff_timeout <= 90):
        parser.error('高度2～8米、起飞超时10～90秒；模型预算/timeout必须为正')
    prompts = json.loads((ROOT/'stage5/convoy_prompts.json').read_text())
    task = next((v for v in prompts['tasks'] if v['id'] == args.prompt_id), None)
    if task is None:
        parser.error('未知prompt-id')
    from stage5.airsim.mission_runtime import SUPPORTED_MODES, SYSTEM_AIRSIM, AirSimFlightRuntime, AirSimQwenAgent
    if task['following_mode'] not in SUPPORTED_MODES:
        parser.error('当前前向相机仅开放pickup后上方候选；侧向/正上方仍待视角与跟踪验收')
    state = json.loads((args.state_dir/'state.json').read_text())
    def cancel():
        if (Path(state['run_dir'])/'land.request.json').exists():
            raise RuntimeError('本轮已请求降落或急停，任务取消；重新任务先down/up')
    if args.action == 'run': cancel()
    config = configuration()
    config.setdefault('DINO_MIN_SCORE', '0.7')
    base = f'http://127.0.0.1:{state["config"]["raw_port"]}'
    config.update(STAGE5_RGB_URL=base+'/rgb', STAGE5_DEPTH_URL=base+'/depth')
    output = Path(state['run_dir'])/('task-'+uuid.uuid4().hex)
    output.mkdir()
    source_paths = [*Path(__file__).parent.glob('*.py'), ROOT/'stage5/agent_runtime.py',
                    ROOT/'stage5/agent_contracts.py', ROOT/'stage5/qwen_agent.py', ROOT/'stage5/convoy_prompts.json',
                    ROOT/'stage5/latency.py', ROOT/'stage5/follow.py', ROOT/'stage5/tactics.py', ROOT/'stage5/task_runner.py']
    write_json(output/'source-identity.json', dict(runtime_run_id=state['run_id'],
        sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}))
    started = time.monotonic()
    def record(event, **fields):
        with (output/'bootstrap.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(event=event, wall_s=time.monotonic()-started, **fields), ensure_ascii=False)+'\n')
    lease = open('/tmp/uav-stage5-follow.lock', 'a+')
    try:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lease.close(); raise SystemExit('已有 Stage5 task，拒绝竞争PX4') from None
    flight = executor = None; arm_attempted = False; boot_complete = False; convoy_started = False
    convoy = ConvoyClient(state['config']['rpc_host'], state['config']['rpc_port'], 4)
    def stop_convoy():
        nonlocal convoy_started
        if convoy_started:
            stopped = convoy.simStopConvoy()
            if not stopped.get('ok'):
                raise RuntimeError('车队停止失败')
            convoy_started = False; record('convoy_stopped')
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    if args.action == 'run':
        signal.signal(signal.SIGTERM, interrupt)
    try:
        report = check(state, config)
        report.update(prompt_id=task['id'], supported_modes=list(SUPPORTED_MODES))
        write_json(output/'health.json', report)
        if not report['ready']:
            print(json.dumps(dict(output=str(output), **report), ensure_ascii=False, indent=2), flush=True)
            return 1
        report.update(ready=False, calibration_ready=False)
        write_json(output/'health.json', report)
        config['CAMERA_MODEL'] = measure_camera(state['config'])
        write_json(output/'calibration.json', config['CAMERA_MODEL'])
        report.update(ready=True, calibration_ready=True)
        write_json(output/'health.json', report)
        print(json.dumps(dict(output=str(output), **report), ensure_ascii=False, indent=2), flush=True)
        if args.action == 'check':
            return 0
        # 外部runtime在检查期间不得被替换。模型检查耗时后重验当前链路。
        current = json.loads((args.state_dir/'state.json').read_text())
        if current['run_id'] != state['run_id'] or not inspect(state)['ready']:
            raise RuntimeError('健康检查后runtime身份/就绪状态已变化')
        flight = Flight('udpin:127.0.0.1:14545')
        if flight.armed:
            raise RuntimeError('拒绝接管已解锁无人机')
        initial = flight.snapshot()['p'].copy()
        write_json(output/'task-input.json', dict(task=task, conventions=prompts['conventions'], run_id=state['run_id'],
                   takeoff_height_m=args.takeoff_height, takeoff_timeout_s=args.takeoff_timeout,
                   dino_min_score=float(config['DINO_MIN_SCORE']),
                   qwen_budget=args.budget, model_task_timeout_s=args.timeout, takeoff_backend='px4_commander',
                   spawn_yaw_deg=state['config']['spawn_yaw_deg']))
        for name, value in (('MIS_TAKEOFF_ALT', args.takeoff_height), ('MPC_TKO_SPEED', .5)):
            px4(state, 'param', 'set', name, str(value))
        cancel()
        arm_attempted = True; record('arm_requested')
        px4(state, 'commander', 'arm')
        arm_deadline = time.monotonic()+5
        while not flight.armed and time.monotonic() < arm_deadline:
            cancel()
            flight.poll(); time.sleep(.02)
        if not flight.armed:
            raise RuntimeError('PX4拒绝解锁')
        cancel()
        px4(state, 'commander', 'takeoff')
        takeoff_started = time.monotonic()
        record('takeoff_dispatched')
        result = queue.Queue(maxsize=1)
        result.put((True, True))  # 仅表示命令派发；await_hover仍以实时估计与Loiter确认完成。
        await_hover(flight, initial, args.takeoff_height, result, args.takeoff_timeout, record, cancel=cancel)
        record_latency(output, 'takeoff_to_hover', time.monotonic()-takeoff_started)
        # 实际悬停确认后才启动车队，爬升期间车辆保持停止。
        cancel()
        convoy_started = True  # 回包超时也可能已经启动，异常时必须尝试停止。
        record('convoy_start_requested')
        convoy_start = time.monotonic()
        car = convoy.simStartConvoy()
        record('convoy_start_response', response=car)
        record_latency(output, 'convoy_start_rpc', time.monotonic()-convoy_start, success=car.get('ok', False))
        if car.get('ok') and car.get('started_now') is False:
            convoy_started = False  # 明确已由别的调用启动时不接管。
            raise RuntimeError('车队已运行，拒绝接管')
        if not car.get('ok') or not car.get('started_now'):
            raise RuntimeError('车队启动失败：'+str(car.get('message', car)))
        record('convoy_started', response=car)
        boot_complete = True
        config.update(STAGE5_BACKEND='airsim', QWEN_SYSTEM=SYSTEM_AIRSIM, AIRSIM_TASK=task, AIRSIM_RUN_DIR=state['run_dir'])
        from task_runner import TaskRunner
        from mission_registry import register
        def factory(deadline):
            nonlocal executor
            executor = AirSimFlightRuntime(config, output, deadline, flight=flight, lease=lease, stop_convoy=stop_convoy)
            return executor
        text = task['prompt']
        runner = TaskRunner(text, AirSimQwenAgent(config), factory, output, args.budget, args.timeout, task.get('duration_s', args.timeout),
            request_timeout=float(config.get('QWEN_TIMEOUT', '45')), summary_timeout=30)
        register(output)
        record('model_task_started')
        code = runner.run()
        if code == 130: request_land(state)
        return code
    except (Exception, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt): boot_complete = False
        record('task_error', error_type=type(exc).__name__)
        (output/'bootstrap-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        write_json(output/'bootstrap-result.json', dict(ok=False, error_type=type(exc).__name__, error_message=str(exc) if isinstance(exc, RuntimeError) else None, boot_complete=boot_complete))
        reason = f'：{exc}' if isinstance(exc, RuntimeError) else ''
        print(f'AirSim task停止：{type(exc).__name__}{reason}；证据 {output}', flush=True)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        # 各自独立恢复，避免停止车队的网络错误阻止飞控恢复。
        try:
            stop_convoy()
        except Exception as exc:
            record('convoy_stop_error', error_type=type(exc).__name__)
        if arm_attempted and not boot_complete:
            try:
                px4(state, 'commander', 'land'); record('recovery_land_requested')
            except Exception as exc:
                record('recovery_land_error', error_type=type(exc).__name__)
        if flight and executor is None:
            if boot_complete and not (Path(state['run_dir'])/'land.request.json').exists():
                try:
                    flight.hold()
                except Exception as exc:
                    record('hold_error', error_type=type(exc).__name__)
            flight.close()
        lease.close()
        try:
            latency = summarize_latency(output)
            write_json(output/'latency-summary.json', latency)
            print('LATENCY '+json.dumps(latency, ensure_ascii=False), flush=True)
        except (OSError, ValueError):
            pass


def main(argv=None):
    values = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--state-dir', type=Path, default=ROOT/'artifacts/stage5-airsim')
    known, _ = parser.parse_known_args(values)
    if values and values[0] == 'run':
        directory=known.state_dir.resolve();directory.mkdir(parents=True,exist_ok=True)
        with management_lock(directory, 'task'):
            return _main(values)
    return _main(values)


if __name__ == '__main__':
    raise SystemExit(main())
