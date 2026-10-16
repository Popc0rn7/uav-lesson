#!/usr/bin/env python3
"""PC：独立 MAVLink Offboard 验收，不启动 ROS、不使用场景真值控制。"""
import argparse
import fcntl
import json
import math
from pathlib import Path
import re
import socket
import time

from pymavlink import mavutil
from runtime import ROOT, ready, px4
from rpc_client import rpc


def trajectory(t, origin):
    """12 秒 XYZ 平滑往返，输出 NED 米、m/s、m/s²。"""
    duration = 12.
    omega = 2 * math.pi / duration
    amplitudes = [.5, .5, -.25]
    t = max(0., min(duration, t))
    return tuple([
        (origin[i] + a * (1 - math.cos(omega * t)) if order == 0 else
         a * omega * math.sin(omega * t) if order == 1 else
         a * omega ** 2 * math.cos(omega * t))
        for i, a in enumerate(amplitudes)] for order in range(3))


def circle_trajectory(t, origin, speed, heading_deg=180.):
    """半径 2 m、两圈，3 秒平滑加减速；最大离起点 4 m。"""
    radius, ramp = 2., 3.
    omega = speed/radius
    cruise = 4*math.pi/omega-ramp
    duration = cruise+2*ramp
    t = max(0., min(duration, t))
    if t < ramp:
        s = t/ramp
        theta = omega*ramp*(s**3-.5*s**4)
        rate = omega*(3*s*s-2*s**3)
        acc = omega*(6*s-6*s*s)/ramp
    elif t < ramp+cruise:
        theta, rate, acc = omega*(t-ramp/2), omega, 0.
    else:
        s = (t-ramp-cruise)/ramp
        theta = 4*math.pi-omega*ramp/2+omega*ramp*(s-s**3+.5*s**4)
        rate = omega*(1-3*s*s+2*s**3)
        acc = -omega*(6*s-6*s*s)/ramp
    sn, cs = math.sin(theta), math.cos(theta)
    h = math.radians(heading_deg)
    def rotate(x,y):
        return [math.cos(h)*x-math.sin(h)*y, math.sin(h)*x+math.cos(h)*y, 0.]
    p = rotate(radius*(1-cs),radius*sn)
    v = rotate(radius*sn*rate,radius*cs*rate)
    a = rotate(radius*(cs*rate**2+sn*acc),radius*(-sn*rate**2+cs*acc))
    return ([origin[i]+p[i] for i in range(3)],v,a), duration


class Check:
    def __init__(self, state, speed=None, heading_deg=180.):
        self.state = state
        self.link = None
        self.messages = {}
        self.received = {}
        self.records = []
        self.last_record = 0.
        self.started = time.monotonic()
        self.speed = speed
        self.heading_deg = heading_deg
        self.envelope_m = 6 if speed is not None else 4
        self.clock_samples = []
        self.clock_reset = False
        self.clock_rate = 1.
        self.last_sim_time = 0.

    def interval(self, message_id):
        self.messages.pop('MESSAGE_INTERVAL',None)
        self.command(510,message_id)
        end=time.monotonic()+3
        while time.monotonic()<end:
            self.pump()
            msg=self.messages.get('MESSAGE_INTERVAL')
            if msg and msg.message_id==message_id:
                return msg.interval_us
            time.sleep(.02)
        raise RuntimeError(f'无法读取消息 {message_id} 的发布周期')

    def pump(self):
        while (msg := self.link.recv_match(blocking=False)) is not None:
            if msg.get_srcSystem() == 1 and msg.get_srcComponent() == 1:
                self.messages[msg.get_type()] = msg
                self.received[msg.get_type()] = time.monotonic()
                if msg.get_type()=='LOCAL_POSITION_NED':
                    stamp=msg.time_boot_ms/1000.
                    if self.clock_samples and stamp<self.clock_samples[-1][1]:
                        self.clock_reset=True
                    if not self.clock_samples or stamp!=self.clock_samples[-1][1]:
                        self.clock_samples.append((time.monotonic(),stamp))
                        self.clock_samples=self.clock_samples[-40:]

    def simulation_time(self):
        """PX4 采样时钟＋最近采样估计的实时率外推，禁止按墙钟推进轨迹。"""
        self.pump()
        if self.clock_reset:
            raise RuntimeError('PX4 仿真时钟复位')
        samples=self.clock_samples
        if not samples or time.monotonic()-samples[-1][0]>1:
            raise RuntimeError('PX4 仿真时钟停流')
        if len(samples)>2 and samples[-1][0]-samples[0][0]>.2:
            mean_wall=sum(x for x,_ in samples)/len(samples)
            mean_sim=sum(y for _,y in samples)/len(samples)
            self.clock_rate=sum((x-mean_wall)*(y-mean_sim) for x,y in samples)/sum((x-mean_wall)**2 for x,_ in samples)
        value=samples[-1][1]+(time.monotonic()-samples[-1][0])*self.clock_rate
        self.last_sim_time=max(value,self.last_sim_time)
        return self.last_sim_time

    def command(self, command, *params):
        self.link.mav.command_long_send(1, 1, command, 0, *(list(params) + [0] * (7-len(params))))

    def local(self):
        self.pump()
        if time.monotonic()-self.received.get('LOCAL_POSITION_NED', 0) > 1:
            raise RuntimeError('PX4 LOCAL_POSITION_NED 停流')
        msg = self.messages['LOCAL_POSITION_NED']
        p, v = [msg.x, msg.y, msg.z], [msg.vx, msg.vy, msg.vz]
        if not all(math.isfinite(x) for x in p+v):
            raise RuntimeError('非有限位置或速度')
        return p, v

    def armed(self):
        self.pump()
        if time.monotonic()-self.received.get('HEARTBEAT', 0) > 3:
            raise RuntimeError('PX4 心跳停流')
        return bool(self.messages['HEARTBEAT'].base_mode & 128)

    def mode(self):
        return mavutil.mode_string_v10(self.messages['HEARTBEAT'])

    def send(self, p, v=None, a=None):
        v = v or [0., 0., 0.]
        a = a or [0., 0., 0.]
        # 位置、速度、加速度、yaw 全部有效；仅忽略 yaw rate。
        stamp = self.messages['LOCAL_POSITION_NED'].time_boot_ms
        self.link.mav.set_position_target_local_ned_send(
            stamp, 1, 1, mavutil.mavlink.MAV_FRAME_LOCAL_NED, 2048,
            *p, *v, *a, self.yaw, 0.)

    def tick(self, label, target=None, reference_v=None, reference_a=None):
        p, v = self.local()
        self.last_tick_stamp=self.messages['LOCAL_POSITION_NED'].time_boot_ms
        sample_received=self.received['LOCAL_POSITION_NED']
        outside = math.dist(p[:2], self.origin[:2]) > self.envelope_m or not self.origin[2]-5 < p[2] < self.origin[2]+1
        if outside and label!='land':
            raise RuntimeError(f'超出 {self.envelope_m} m 水平 / 5 m 高度包络')
        now = time.monotonic()
        if now-self.last_record > .09:
            self.records.append(dict(t=now-self.started, label=label, p=p, v=v,
                                     target=target, mode=self.mode(), armed=self.armed(),
                                     reference_velocity=reference_v, reference_acceleration=reference_a,
                                     px4_time_boot_ms=self.last_tick_stamp,
                                     position_age_wall_s=now-sample_received,
                                     outside_envelope=outside,simulation_rate=self.clock_rate))
            self.last_record = now
        self.link.mav.heartbeat_send(6, 8, 0, 0, 4)
        time.sleep(.02)
        return p, v

    def hold(self, label, target, seconds, require_offboard=True):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            self.send(target)
            self.tick(label, target)
            if require_offboard and self.mode() != 'OFFBOARD':
                raise RuntimeError(f'意外退出 Offboard: {self.mode()}')

    def land(self, request=True):
        if request:
            self.command(mavutil.mavlink.MAV_CMD_NAV_LAND)
        end = time.monotonic()+55
        retry = 0.
        while time.monotonic() < end:
            self.pump()
            landed = self.messages.get('EXTENDED_SYS_STATE')
            if (landed and time.monotonic()-self.received['EXTENDED_SYS_STATE'] < 2
                    and landed.landed_state == 1):
                self.command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0)
                time.sleep(.3)
                if not self.armed():
                    result = px4(self.state, 'commander', 'mode', 'auto:loiter')
                    if result.returncode:
                        raise RuntimeError(result.stdout+result.stderr)
                    p, v = self.local()
                    self.records.append(dict(t=time.monotonic()-self.started, label='landed-disarmed',
                                             p=p, v=v, armed=False, landed=1))
                    return
            if request and time.monotonic() > retry:
                self.command(mavutil.mavlink.MAV_CMD_NAV_LAND)
                retry = time.monotonic()+2
            self.tick('land')
        raise RuntimeError('未在 55 秒内确认落地并解除解锁')

    def run(self, output):
        original = {}
        intervals = {}
        control_started = False
        error = None
        metrics = {}
        try:
            # 复用本入口 PX4 默认 payload 链路，不动态创建/销毁飞控发布者。
            # udpin 内部允许地址复用，因此先以独占 bind 拒绝已有客户端。
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.bind(('127.0.0.1', 14030))
            self.link = mavutil.mavlink_connection('udpin:127.0.0.1:14030', source_system=245)
            end = time.monotonic()+10
            while not all(k in self.messages for k in ('HEARTBEAT','LOCAL_POSITION_NED','ATTITUDE','EXTENDED_SYS_STATE')):
                self.pump()
                if time.monotonic() > end:
                    raise RuntimeError('等待诊断遥测超时')
                time.sleep(.05)
            if self.armed() or self.messages['EXTENDED_SYS_STATE'].landed_state != 1:
                raise RuntimeError('必须从已落地、未解锁状态开始')
            self.origin, _ = self.local()
            self.yaw = self.messages['ATTITUDE'].yaw
            if self.speed is not None:
                for message_id, interval in [(24,-1),(105,-1),(32,20000)]:
                    intervals[message_id]=self.interval(message_id)
                    self.command(511,message_id,interval)
                    time.sleep(.1)
                metrics['px4_limits']={}
                for name in ['MPC_XY_VEL_MAX','MPC_ACC_HOR_MAX','MPC_TILTMAX_AIR']:
                    raw=px4(self.state,'param','show',name)
                    value=float(re.search(r':\s*([-0-9.]+)',raw.stdout)[1])
                    metrics['px4_limits'][name]=value
                if metrics['px4_limits']['MPC_XY_VEL_MAX']<self.speed:
                    raise RuntimeError('PX4 速度上限低于测试档位；不自动放宽限制')
            for name, value in [('COM_RC_IN_MODE',4), ('COM_OF_LOSS_T',.5), ('COM_OBL_RC_ACT',4)]:
                raw = px4(self.state, 'param', 'show', name)
                original[name] = float(re.search(r':\s*([-0-9.]+)', raw.stdout)[1])
                result = px4(self.state, 'param', 'set', name, str(value))
                if result.returncode:
                    raise RuntimeError(result.stdout+result.stderr)
            target = [*self.origin[:2], self.origin[2]-2.]
            print('Offboard 预发送 → 起飞 2 m', flush=True)
            self.hold('prestream', target, 2.5, False)
            control_started = True
            self.command(mavutil.mavlink.MAV_CMD_DO_SET_MODE, 1, 6)
            self.command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)
            deadline = time.monotonic()+25
            while True:
                self.send(target)
                p, v = self.tick('takeoff', target)
                if self.armed() and self.mode() == 'OFFBOARD' and math.dist(p,target)<.25 and math.dist(v,[0,0,0])<.3:
                    break
                if time.monotonic()>deadline:
                    raise RuntimeError('Offboard 解锁/起飞/稳定超时')
            self.hold('hover',target,3)
            collision_before=rpc('simGetCollisionInfo','PX4')
            truth_before=rpc('simGetVehiclePose','PX4')
            duration=12 if self.speed is None else circle_trajectory(0,target,self.speed,self.heading_deg)[1]
            label='xyz' if self.speed is None else 'circle'
            print(f'执行 {duration:.2f} 秒 {label}，参考速度 {self.speed} m/s', flush=True)
            start = self.simulation_time()
            errors = []
            speeds = []
            metrics['reference_timebase']='PX4 LOCAL_POSITION_NED sample time with rate extrapolation'
            metrics['error_timebase']='reference evaluated at PX4 measurement timestamp'
            def reference(elapsed):
                return (trajectory(elapsed,target) if self.speed is None else
                        circle_trajectory(elapsed,target,self.speed,self.heading_deg)[0])
            while self.simulation_time()-start < duration:
                elapsed=self.simulation_time()-start
                p,v,a=reference(elapsed)
                self.send(p,v,a)
                record_count=len(self.records)
                actual, velocity = self.tick(label,p,v,a)
                evaluation_target=reference(self.last_tick_stamp/1000.-start)[0]
                errors.append(math.dist(actual,evaluation_target))
                if len(self.records)>record_count:
                    self.records[-1].update(evaluation_target=evaluation_target,tracking_error_m=errors[-1])
                speeds.append(math.dist(velocity,[0,0,0]))
                metrics.update(xyz_rmse_m=math.sqrt(sum(x*x for x in errors)/len(errors)),
                               xyz_max_error_m=max(errors),actual_peak_speed_m_s=max(speeds),
                               simulation_rate=self.clock_rate)
                if self.speed is not None and errors[-1]>.8:
                    self.records.append(dict(t=time.monotonic()-self.started,label='tracking-error',
                                             p=actual,v=velocity,target=p,evaluation_target=evaluation_target,
                                             tracking_error_m=errors[-1],px4_time_boot_ms=self.last_tick_stamp))
                    raise RuntimeError('圆周实时跟踪误差超过 0.8 m；停止升档')
                if self.mode() != 'OFFBOARD':
                    raise RuntimeError(f'XYZ 执行退出 Offboard: {self.mode()}')
            self.hold('return',target,3)
            collision_after=rpc('simGetCollisionInfo','PX4')
            metrics['collision_before']=collision_before
            metrics['collision_after']=collision_after
            metrics['truth_before']=truth_before
            metrics['truth_after']=rpc('simGetVehiclePose','PX4')
            if collision_after['time_stamp']!=collision_before['time_stamp']:
                raise RuntimeError('轨迹期间发生新碰撞')
            metrics.update(xyz_rmse_m=math.sqrt(sum(x*x for x in errors)/len(errors)),
                           xyz_max_error_m=max(errors), return_error_m=math.dist(self.local()[0],target),
                           actual_peak_speed_m_s=max(speeds))
            metrics['simulation_rate']=self.clock_rate
            if self.speed is not None and max(speeds)<self.speed*.8:
                raise RuntimeError('实测峰值速度未达到参考档位的 80%')
            if metrics['xyz_max_error_m'] > .8 or metrics['return_error_m'] > .3:
                raise RuntimeError('XYZ 跟踪/返回误差超过 0.8/0.3 m')
            # 停止设定值，但保留 MAVLink 心跳和遥测，区分 Offboard 失流与断链。
            loss_at = time.monotonic()
            print('停止设定值，验证 PX4 自动降落', flush=True)
            while self.mode() == 'OFFBOARD':
                self.tick('setpoint-loss')
                if time.monotonic()-loss_at>5:
                    raise RuntimeError('设定值停流后 5 秒仍未退出 Offboard')
            metrics['loss_exit_wall_s'] = time.monotonic()-loss_at
            metrics['loss_mode'] = self.mode()
            if self.mode() != 'LAND':
                raise RuntimeError(f'停流后未自动进入降落: {self.mode()}')
            self.land(request=False)
            metrics['loss_landed_disarmed'] = True
            control_started = False
        except BaseException as exc:
            error = f'{type(exc).__name__}: {exc}'
        finally:
            if control_started:
                try:
                    self.land()
                except Exception as exc:
                    error = (error or '')+f' cleanup landing: {exc}'
            for name, value in original.items():
                result = px4(self.state,'param','set',name,str(value))
                if result.returncode:
                    error = (error or '')+f' restore {name}: {result.stdout}{result.stderr}'
            if self.link:
                for message_id, interval in intervals.items():
                    try:
                        # 此 PX4 的 GET 返回 -1 表示默认事件驱动流，0 表示已停流；
                        # SET 的 -1 却表示禁用，恢复默认必须发 0，不能原样回写。
                        setting = interval if interval>0 else (0 if interval<0 else -1)
                        self.command(511,message_id,setting)
                        time.sleep(.1)
                        if self.interval(message_id)!=interval:
                            raise RuntimeError('周期恢复值不一致')
                    except Exception as exc:
                        error=(error or '')+f' stream restore {message_id}: {exc}'
                self.link.close()
            if error is None:
                try:
                    metrics['ready_after_cleanup'] = ready(self.state)
                    if not metrics['ready_after_cleanup']:
                        raise RuntimeError('清理后健康检查未通过')
                except Exception as exc:
                    error = f'cleanup health: {exc}'
            output.write_text(json.dumps(dict(passed=error is None,error=error,metrics=metrics,
                                             parameters=original,intervals=intervals,
                                             profile=dict(speed_m_s=self.speed,heading_deg=self.heading_deg,
                                                          envelope_m=self.envelope_m),records=self.records),indent=2))
            print(json.dumps(dict(report=str(output),error=error,metrics=metrics),ensure_ascii=False),flush=True)
        if error:
            raise RuntimeError(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true',help='执行仿真解锁、XYZ 和停流降落')
    parser.add_argument('--state-dir',type=Path,default=ROOT/'artifacts/airsim-runtime')
    parser.add_argument('--speed',type=float,choices=[1.,2.,3.],help='已检查空域内的 2 m 半径水平圆周速度档')
    parser.add_argument('--heading-deg',type=float,default=180.,help='圆周中心相对起点的 NED 方位角，度')
    args = parser.parse_args()
    if not args.run:
        parser.error('需要 --run 显式执行飞行')
    if not math.isfinite(args.heading_deg):
        parser.error('heading-deg 必须为有限角度')
    with (args.state_dir/'runtime.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state = json.loads((args.state_dir/'state.json').read_text())
        if state.get('ros_container'):
            raise RuntimeError('当前为 SUPER 控制模式，拒绝并行 MAVLink 控制；先落地 down 后启动独立 PX4 配置')
        if state['phase'] != 'ready' or not ready(state):
            raise RuntimeError('当前管理实例未就绪')
        output=Path(state['run_dir'])/f'offboard-{time.time_ns()}.json'
        Check(state,args.speed,args.heading_deg).run(output)


if __name__ == '__main__':
    main()
