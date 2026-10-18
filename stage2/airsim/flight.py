"""PC：直接 MAVLink 验证 PX4 起降、Offboard 失流与控制权交还。"""
import json
import math
from pathlib import Path
import re
import socket
import shutil
import time

from pymavlink import mavutil
from verify_offboard import Check
from runtime import px4, owned_container, host_alive
from session import rpc


class ControlReleased(RuntimeError):
    """飞控模式已被外部改变；当前控制器永久停止设定值和模式指令。"""


class FlightCheck(Check):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.control_active = False
        self.control_yielded = False
        self.yielded_mode = None
        self.armed_seen = False
        self.landing = False
        self.setpoints_enabled = True
        self.setpoint_count = 0
        self.last_setpoint_wall = None
        self.max_setpoint_gap_s = 0.
        self.acks = {}
        self.confirmed_commands = []

    def check_owner(self, require_fresh=True):
        if self.control_yielded:
            raise ControlReleased(f'控制已交还：{self.yielded_mode}')
        if not self.control_active:
            return
        self.pump()
        # 没有新心跳时走通信异常/失流处理，不能据旧模式推断人工接管。
        if time.monotonic()-self.received.get('HEARTBEAT', 0) > 3:
            if require_fresh:
                raise RuntimeError('PX4 心跳停流')
            return
        heartbeat = self.messages['HEARTBEAT']
        mode = self.mode()
        allowed = {'OFFBOARD', 'LAND'} if self.landing else {'OFFBOARD'}
        disarmed = self.armed_seen and not heartbeat.base_mode & 128 and not self.landing
        if mode not in allowed or disarmed:
            self.control_yielded = True
            self.yielded_mode = 'DISARMED' if disarmed else mode
            self.setpoints_enabled = False
            self.control_active = False
            raise ControlReleased(f'检测到外部模式/解锁状态变化，交还控制：{self.yielded_mode}')

    def send(self, *args, **kwargs):
        self.check_owner()
        if not self.setpoints_enabled:
            raise RuntimeError('设定值已停止，不允许本轮重新进入 Offboard')
        now = time.monotonic()
        if self.last_setpoint_wall is not None:
            self.max_setpoint_gap_s = max(self.max_setpoint_gap_s, now-self.last_setpoint_wall)
        super().send(*args, **kwargs)
        self.last_setpoint_wall = now
        self.setpoint_count += 1

    def command(self, *args):
        self.check_owner(require_fresh=not self.landing)
        super().command(*args)

    def confirmed_command(self, command, params, target, predicate, label, timeout=6):
        self.acks.pop(command, None)
        self.command(command, *params)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            self.send(target)
            self.tick(label, target)
            ack = self.acks.get(command)
            if ack and ack.result not in (mavutil.mavlink.MAV_RESULT_ACCEPTED,
                                           mavutil.mavlink.MAV_RESULT_IN_PROGRESS):
                raise RuntimeError(f'PX4 拒绝命令 {command}: result={ack.result}')
            if ack and ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED and predicate():
                self.confirmed_commands.append(dict(command=command, result=ack.result,
                    mode=self.mode(), armed=self.armed(),
                    elapsed_wall_s=time.monotonic()-(deadline-timeout)))
                return
        raise RuntimeError(f'PX4 命令 {command} ACK/状态确认超时')

    def land(self, request=True):
        self.check_owner(require_fresh=False)
        self.landing = True
        self.setpoints_enabled = False
        super().land(request=request)
        self.control_active = False

    def pump(self):
        while (msg := self.link.recv_match(blocking=False)) is not None:
            if msg.get_srcSystem() != 1 or msg.get_srcComponent() != 1:
                continue
            # 旧 ADRL 将自身 GCS 心跳也标成 1/1，PX4 会转发到 payload 链路。
            # 只有真正的 PX4 autopilot 心跳能决定飞控模式与解锁状态。
            if msg.get_type() == 'HEARTBEAT' and msg.autopilot != mavutil.mavlink.MAV_AUTOPILOT_PX4:
                continue
            if msg.get_type() == 'COMMAND_ACK':
                if getattr(msg, 'target_system', 0) in (0, 245):
                    self.acks[msg.command] = msg
            self.messages[msg.get_type()] = msg
            self.received[msg.get_type()] = time.monotonic()
            if msg.get_type() == 'LOCAL_POSITION_NED':
                stamp = msg.time_boot_ms/1000
                if self.clock_samples and stamp < self.clock_samples[-1][1]:
                    self.clock_reset = True
                if not self.clock_samples or stamp != self.clock_samples[-1][1]:
                    self.clock_samples.append((time.monotonic(), stamp))
                    self.clock_samples = self.clock_samples[-40:]

    def tick(self, label, *args, **kwargs):
        if label != 'handoff-observe':
            self.check_owner()
        if label != 'land' and (Path(self.state['run_dir'])/'land.request').exists():
            raise RuntimeError('用户已请求降落/停止，本轮飞行取消')
        return super().tick(label, *args, **kwargs)


def review_ulog(report_path):
    """将 uint32 MAVLink 时钟对齐到 ULog，复用 SUPER 的只读复盘指标。"""
    report = json.loads(report_path.read_text())
    result = {'source_report': str(report_path)}
    try:
        from pyulog import ULog
        from review_flight import analyse_ulog
        samples = [s for s in report['samples'] if s['label'] == 'round-trip']
        candidates = sorted((report_path.parent/'px4-logs').rglob('*.ulg'))
        if not samples or not candidates:
            raise RuntimeError('没有往返样本或本轮 ULog；不生成零误差结论')
        path = report_path.with_suffix('.ulg')
        shutil.copy2(candidates[-1], path)
        log = ULog(str(path), message_name_filter_list=['vehicle_local_position'])
        wrap = (2**32)/1000
        offset = round((log.start_timestamp/1e6-samples[0]['px4_time_boot_ms']/1000)/wrap)*wrap
        interval = [offset+samples[0]['px4_time_boot_ms']/1000,
                    offset+samples[-1]['px4_time_boot_ms']/1000]
        metrics, _ = analyse_ulog(path, [interval])
        result.update(ulog=str(path), interval=interval, metrics=metrics)
    except Exception as exc:
        result['limitation'] = str(exc)
    review_path = report_path.with_suffix('.ulog-review.json')
    review_path.write_text(json.dumps(result, indent=2)+'\n')
    print(f'ULog 复盘：{review_path}', flush=True)
    if 'limitation' in result:
        print('ULog 复盘限制：'+result['limitation'], flush=True)


def fly(state, finish="land"):
    if state.get('race', {}).get('phase') != 'racing':
        raise RuntimeError('尚未开始原生比赛；先执行 race.py start-race，再运行控制器')
    if not rpc(state, 'simGetDisqualified', 'drone_2'):
        raise RuntimeError('原生比赛已结束或被复位；停止控制，先 reset-race / start-race')
    if not host_alive(state) or not owned_container(state):
        raise RuntimeError('当前场景/PX4 身份不匹配')
    check = FlightCheck(state)
    if (Path(state['run_dir'])/'land.request').exists():
        raise RuntimeError('本轮已取消；重新试飞需要 down/up')
    originals = {}
    started = False
    error = None
    metrics = {}
    output = Path(state['run_dir'])/f'flight-{time.time_ns()}.json'
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(('127.0.0.1', 14030))
        check.link = mavutil.mavlink_connection('udpin:127.0.0.1:14030', source_system=245)
        deadline = time.monotonic()+12
        while not all(k in check.messages for k in ('HEARTBEAT', 'LOCAL_POSITION_NED', 'ATTITUDE', 'EXTENDED_SYS_STATE')):
            check.pump()
            if time.monotonic() > deadline:
                raise RuntimeError('等待 PX4 遥测超时')
            time.sleep(.02)
        if check.armed() or check.messages['EXTENDED_SYS_STATE'].landed_state != 1:
            raise RuntimeError('必须从落地且未解锁状态开始')
        check.origin, _ = check.local()
        check.yaw = check.messages['ATTITUDE'].yaw
        for name, value in [('COM_RC_IN_MODE', 4), ('COM_OF_LOSS_T', .5), ('COM_OBL_RC_ACT', 4)]:
            result = px4(state, 'param', 'show', name)
            match = re.search(r':\s*([-0-9.]+)', result.stdout)
            if result.returncode or not match:
                raise RuntimeError(f'无法读取 {name}: {result.stdout}{result.stderr}')
            originals[name] = float(match[1])
            result = px4(state, 'param', 'set', name, str(value))
            if result.returncode:
                raise RuntimeError(result.stdout+result.stderr)
        target = [check.origin[0], check.origin[1], check.origin[2]-2]
        print('直接 PX4：预发送 → 解锁 → 起飞 2 m', flush=True)
        check.hold('prestream', target, 2.5, False)
        if (Path(state['run_dir'])/'land.request').exists():
            raise RuntimeError('用户已取消本轮，拒绝解锁')
        check.confirmed_command(mavutil.mavlink.MAV_CMD_DO_SET_MODE, [1, 6], target,
                                lambda: check.mode() == 'OFFBOARD', 'enter-offboard')
        check.control_active = True
        started = True
        check.confirmed_command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, [1], target,
                                check.armed, 'arm')
        check.armed_seen = True
        deadline = time.monotonic()+35
        while True:
            check.send(target)
            p, v = check.tick('takeoff', target)
            if check.armed() and check.mode() == 'OFFBOARD' and math.dist(p, target) < .25 and math.dist(v, [0, 0, 0]) < .3:
                break
            if time.monotonic() > deadline:
                raise RuntimeError('解锁/起飞/稳定超时')
        check.hold('hover', target, 3)
        collision_before = rpc(state, 'simGetCollisionInfo', 'PX4')
        metrics['collision_before'] = collision_before
        start = check.simulation_time()
        print('直接 PX4：峰值约 0.262 m/s 平滑 1 m 往返，NED 本地坐标', flush=True)
        errors = []
        while (elapsed := check.simulation_time()-start) < 12:
            # 与 SUPER 独立诊断一致按 PX4 仿真时间推进，峰值约 0.262 m/s。
            omega = math.pi/6
            target_now = [target[0]+.5*(1-math.cos(omega*elapsed)), target[1], target[2]]
            velocity = [.5*omega*math.sin(omega*elapsed), 0, 0]
            acceleration = [.5*omega**2*math.cos(omega*elapsed), 0, 0]
            check.send(target_now, velocity, acceleration)
            p, _ = check.tick('round-trip', target_now, velocity, acceleration)
            if check.mode() != 'OFFBOARD':
                raise RuntimeError(f'意外退出 Offboard: {check.mode()}')
            sample_elapsed = check.last_tick_stamp/1000-start
            expected = [target[0]+.5*(1-math.cos(omega*sample_elapsed)), target[1], target[2]]
            errors.append(math.dist(p, expected))
            # API 真值仅评测碰撞；位置闭环使用 PX4 估计。
            if len(check.records) % 10 == 0:
                collision = rpc(state, 'simGetCollisionInfo', 'PX4')
                if collision['time_stamp'] != collision_before['time_stamp']:
                    raise RuntimeError('往返期间发生新碰撞')
        check.hold('return', target, 3)
        metrics.update(max_tracking_error_m=max(errors), return_error_m=math.dist(check.local()[0], target),
                       collision_after=rpc(state, 'simGetCollisionInfo', 'PX4'))
        if metrics['collision_after']['time_stamp'] != collision_before['time_stamp']:
            raise RuntimeError('往返期间发生新碰撞')
        if metrics['max_tracking_error_m'] > .8 or metrics['return_error_m'] > .3:
            raise RuntimeError('短程跟踪/返回误差超过 0.8/0.3 m')
        if finish == 'loss':
            print('停止设定值，保留链路心跳，验证 PX4 Offboard 失流降落', flush=True)
            check.setpoints_enabled = False
            check.landing = True
            loss_at = time.monotonic()
            while check.mode() == 'OFFBOARD':
                check.tick('setpoint-loss')
                if time.monotonic()-loss_at > 5:
                    raise RuntimeError('设定值停流后 5 秒仍未退出 Offboard')
            metrics.update(loss_exit_wall_s=time.monotonic()-loss_at, loss_mode=check.mode())
            if check.mode() != 'LAND':
                raise RuntimeError(f'失流后未进入 LAND: {check.mode()}')
            check.land(request=False)
            started = False
            metrics['loss_landed_disarmed'] = True
            metrics['landed_disarmed'] = True
        elif finish == 'handoff':
            print('模拟外部切换 Hold，验证控制器退出且不抢回控制', flush=True)
            # 这里扮演 QGC 的模式请求；之后生产控制器走与外部接管相同的退出路径。
            check.command(mavutil.mavlink.MAV_CMD_DO_SET_MODE, 1, 4, 3)
            deadline = time.monotonic()+6
            try:
                while time.monotonic() < deadline:
                    check.tick('handoff-wait')
                raise RuntimeError('未观察到外部 Hold 接管')
            except ControlReleased:
                if check.yielded_mode != 'LOITER':
                    raise
            stopped_count = check.setpoint_count
            deadline = time.monotonic()+2
            while time.monotonic() < deadline:
                check.pump()
                if check.mode() != 'LOITER' or not check.armed():
                    raise RuntimeError('Hold 接管后模式/解锁状态异常')
                check.tick('handoff-observe')
            started = False
            metrics.update(handoff_confirmed=True, handoff_mode='LOITER',
                           handoff_observation_wall_s=2, setpoints_after_handoff=check.setpoint_count-stopped_count,
                           landed_disarmed=False)
            print('已交还 Hold；验证结束后用 race.py land 请求降落，当前控制器不会再发模式或设定值', flush=True)
        else:
            print('直接 PX4：降落并确认解除解锁', flush=True)
            check.land()
            started = False
            metrics['landed_disarmed'] = True
    except ControlReleased as exc:
        started = False
        metrics.update(control_released=True, released_mode=check.yielded_mode)
        error = str(exc)
    except BaseException as exc:
        error = f'{type(exc).__name__}: {exc}'
    finally:
        if started:
            try:
                check.land()
                metrics['cleanup_landed_disarmed'] = True
                started = False
            except ControlReleased as exc:
                metrics.update(control_released=True, released_mode=check.yielded_mode)
                error = (error or '')+f'; {exc}'
            except Exception as exc:
                error = (error or '')+f'; cleanup landing: {exc}'
        restored = {}
        if started and not check.control_yielded:
            # 未确认落地时保留失流降落配置，不在异常恢复途中提前恢复旧策略。
            metrics['parameters_restore_deferred'] = originals.copy()
        for name, value in (originals.items() if not started or check.control_yielded else []):
            result = px4(state, 'param', 'set', name, str(value))
            if result.returncode:
                error = (error or '')+f'; restore {name}: {result.stdout}{result.stderr}'
                continue
            raw = px4(state, 'param', 'show', name)
            match = re.search(r':\s*([-0-9.]+)', raw.stdout)
            if raw.returncode or not match or not math.isclose(float(match[1]), value, abs_tol=1e-6):
                error = (error or '')+f'; restore verification failed: {name}'
            else:
                restored[name] = float(match[1])
        metrics['parameters_restored'] = restored
        metrics.update(finish=finish, acknowledgements=check.confirmed_commands,
                       setpoint_count=check.setpoint_count,
                       max_setpoint_gap_wall_s=check.max_setpoint_gap_s)
        if check.link:
            check.link.close()
        output.write_text(json.dumps(dict(success=error is None, error=error, metrics=metrics,
            parameters_before=originals, samples=check.records), indent=2)+'\n')
        print(json.dumps(dict(success=error is None, error=error, report=str(output), metrics=metrics)), flush=True)
    review_ulog(output)
    if error:
        raise RuntimeError(error)
