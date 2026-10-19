#!/usr/bin/env python3
"""PC：DINO 确认红色方块目标，RGB/D 跟踪，Jev 选行为，MAVLink 驱动 PX4。

只用于当前 Stage 5 仿真。车辆真值不进入感知或控制。
"""
import argparse
import fcntl
from collections import deque
import json
import math
import os
import signal
from pathlib import Path
import subprocess
import tempfile
import threading
import time

import numpy as np
from pymavlink import mavutil

from dino_client import DinoClient, camera_png, configuration, paired_frames
from depth_fusion import calibration
from tactics import Tactician, MANEUVERS
from voxel_scene import build
from planner import validate_plan


def rotation(q):
    w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)],
                     [2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)],
                     [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]])


def camera_to_ned(point, own):
    point=np.asarray(point)
    frd=np.array([point[0]+.186,-point[1],-point[2]-.025])
    return own['p']+rotation(own['q'])@frd


def target_surface(rgb, depth, model):
    """当前红方块场景的颜色跟踪；不是通用分割或物体 ID 掩膜。"""
    rm, pixels = rgb
    dm, raw = depth
    for meta, expected, fmt in ((rm,model['rgb'],'RGB_INT8'),(dm,model['depth'],'R_FLOAT32')):
        if (meta['width'],meta['height'],meta['format']) != (expected['width'],expected['height'],fmt):
            raise ValueError('跟踪图像与标准机标定不符')
    image = np.ndarray((rm['height'], rm['width'], 3), dtype=np.uint8, buffer=pixels,
                       strides=(rm['step'], 3, 1))
    r, g, b = (image[:,:,i].astype(np.float32) for i in range(3))
    mask = (r > 60) & (r > 1.6*g) & (r > 1.6*b)
    ys, xs = np.nonzero(mask)
    if len(xs) < 40:
        return None
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()+1), int(ys.max()+1)]
    # 降采样颜色像素，按共光心针孔模型读取对应深度。
    xs, ys = xs[::3], ys[::3]
    ir, idp = model['rgb'], model['depth']
    u = np.rint((xs+.5-ir['cx'])/ir['fx']*idp['fx']+idp['cx']-.5).astype(int)
    v = np.rint((ys+.5-ir['cy'])/ir['fy']*idp['fy']+idp['cy']-.5).astype(int)
    keep = (u >= 0)&(u < idp['width'])&(v >= 0)&(v < idp['height'])
    u, v = u[keep], v[keep]
    depths = np.ndarray((dm['height'],dm['width']), dtype='<f4', buffer=raw,
                        strides=(dm['step'],4))
    x = depths[v,u].astype(float)
    keep = np.isfinite(x)&(x > model['near_m'])&(x < model['far_m'])
    if keep.sum() < 30:
        return None
    x, u, v = x[keep], u[keep], v[keep]
    points = np.column_stack((x, -(u+.5-idp['cx'])/idp['fx']*x,
                              -(v+.5-idp['cy'])/idp['fy']*x))
    point = np.median(points, axis=0)
    return dict(position_camera_flu_m=point.tolist(), box_xyxy=bbox,
                pixels=int(mask.sum()), depth_pixels=int(len(points)),
                range_m=float(np.linalg.norm(point)))


def forward_clearance(depth, model):
    meta, raw = depth
    d = model['depth']
    image = np.ndarray((meta['height'],meta['width']), dtype='<f4', buffer=raw,
                       strides=(meta['step'],4))[::4,::4]
    yy, xx = np.mgrid[0:meta['height']:4,0:meta['width']:4]
    left = -(xx+.5-d['cx'])/d['fx']*image
    up = -(yy+.5-d['cy'])/d['fy']*image
    valid = np.isfinite(image)&(image > model['near_m'])&(image < model['far_m'])
    in_path = valid&(np.abs(left) < .75)&(np.abs(up+.025) < .75)
    return float(image[in_path].min()) if in_path.any() else model['far_m']


def follow_questions(stage=None, simple=False):
    from decision_client import Choice, Score, Noul
    if simple:
        criteria = {key: MANEUVERS[key] for key in stage['allowed_skills']}
        if 'hold_course' in criteria:
            criteria['hold_course'] = '启用当前stage的后上方位置/速度反馈跟随技能；不是固定航向直飞。'
        return {
            'maneuver': Choice(instructions='依据当前stage与最新观测选择行为。目标未确认/不可见时保持位置；本版没有主动搜索技能。'
                '显式仿真策略允许没有已知阻挡的near-frustum unknown限速跟随。', criteria=criteria),
            'risk': Score(instructions='当前移动风险',criteria=['open street','uncertain but no measured blockage','immediate obstacle']),
            'stage_reason': Choice(instructions='解释当前阶段判断。接近目标时即使valid_follow_s=0也属于approaching，不能据此failed。'
                'tracking_lost必须有execution_health.failure_facts.tracking_lost证据；blocked必须有blocked证据。',
                criteria={'observing':'正在观察确认','approaching':'正在接近达标位置','following':'已进入有效跟随',
                          'achieved':'完成标准已达到','tracking_lost':'持续无可用跟踪且无法主动搜索','blocked':'路径存在实际阻挡'}),
            'stage_status': Choice(instructions='只判断当前stage：running继续；done认为目标已达到，交Qwen验收；failed认为无法继续。'
                'observe_target根据可靠目标观测完成；follow_red_vehicle必须结合progress.valid_follow_s与stage.duration_s，'
                '没有达到持续时间不要done。接近过程中误差仍大、有效时长为0不是失败；预算和阶段timeout由执行器处理。只有明确失败事实才failed：持续丢失或实际阻挡。目标短暂丢失可running等待，无法重新确认则failed。execution_health给出连续无跟踪时长和恢复能力；没有搜索技能时，不能无限reacquire。语义候选too_far不等于当前可跟踪。observe只需可靠确认，不要等待跟随时长。不计算预算、不决定后续计划。',
                criteria={'running':'继续本阶段','done':'认为当前阶段目标已达到','failed':'无法继续当前阶段'})}
    options = dict(MANEUVERS)
    options.update(hold_course='启用后上方跟随技能：位置/速度反馈保持8米水平间距、上方2米。'
        '目标已由 DINO 确认并被颜色/RGBD连续跟踪。此动作可前进、减速、后退调整间距，不是盲目朝目标直飞。'
        '当前仿真允许 near-frustum unknown 以1.2m/s限速试探；看到路径阻挡或跟踪丢失则不可跟随。',
        brake='保持位置。目标丢失、路径已知阻挡、观测过期或目标身份未确认时选择。',
        reacquire='保持位置并朝最后目标方向观察，等待重新找到红色目标。',
        gap_left='本版未实现，不选择。',gap_right='本版未实现，不选择。',climb='本版未实现，不选择。')
    if stage:
        options['hold_course']=f"启用当前 stage 的后上方跟随技能：水平{stage['horizontal_distance_m']}米，上方{stage['above_m']}米。仅目标已确认、观测新鲜且路径没有已知阻挡时选择。"
    result={'maneuver':Choice(instructions='选择跟随、暂停或重新观察。不要因初始车辆静止而放弃任务。'
                '有可靠跟踪且路径没有测到阻挡时，应启用跟随技能。运动方向由视觉历史估计，初始采用机头方向。',criteria=options),
            'risk':Score(instructions='评估当前跟随风险',criteria=['open street','uncertain but no measured blockage','immediate obstacle']),
            'target_ambiguous':Noul(instructions='当前已确认的红色目标跟踪是否失效？',
                criteria={'true':'未确认目标或连续观测已丢失','false':'DINO已确认且当前RGBD跟踪稳定'})}
    if stage:
        result['stage_status']=Choice(instructions='根据输入 stage、completion_criteria 和 progress 判断当前阶段状态。'
            '只有 progress.valid_follow_s 达到 duration_s 且跟踪仍可靠才能 completed；不得将一次看到目标视为持续跟随完成。',
            criteria={'running':'继续本阶段','completed':'完成标准已有观测证据支持',
                      'blocked':'暂时无法执行，保持观察','needs_replan':'当前任务或技能不适用，需要规划者处理'})
    return result


class Flight:
    def __init__(self, endpoint, timeout=10):
        self.link = mavutil.mavlink_connection(endpoint, source_system=245, source_component=191)
        self.lock = threading.Lock()
        self.pose = self.q = None
        self.velocity = np.zeros(3)
        self.pose_at = self.q_at = 0
        self.mode = None
        self.armed = False
        self.system = self.component = None
        self.heartbeat_at = self.last_hb = 0
        self.stream_stop=threading.Event()
        self.stream_thread=None
        self.stream_lock=threading.Lock()
        self.stream_command=None
        deadline = time.monotonic()+timeout
        while self.pose is None or self.q is None or self.system is None:
            self.poll()
            if time.monotonic() > deadline:
                raise RuntimeError('PX4 MAVLink 位姿等待超时')
            if self.system is not None and self.component is not None:
                for msg_id in (32,31):
                    self.command(mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,msg_id,20000)
            time.sleep(.05)

    def poll(self):
        for _ in range(200):
            msg = self.link.recv_match(blocking=False)
            if msg is None:
                break
            now = time.monotonic()
            if msg.get_type() == 'HEARTBEAT' and msg.autopilot == mavutil.mavlink.MAV_AUTOPILOT_PX4:
                if msg.get_srcSystem() != 6:
                    continue
                self.system, self.component = msg.get_srcSystem(), msg.get_srcComponent()
                self.mode = (msg.custom_mode >> 16)&255
                self.armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                self.heartbeat_at = now
            elif msg.get_type() == 'LOCAL_POSITION_NED':
                if msg.get_srcSystem() != 6:continue
                with self.lock:
                    self.pose, self.velocity = np.array([msg.x,msg.y,msg.z]), np.array([msg.vx,msg.vy,msg.vz])
                    self.pose_at = now
            elif msg.get_type() == 'ATTITUDE_QUATERNION':
                if msg.get_srcSystem() != 6:continue
                with self.lock:
                    self.q, self.q_at = np.array([msg.q1,msg.q2,msg.q3,msg.q4]), now

    def snapshot(self):
        with self.lock:
            if self.pose is None or self.q is None:
                return None
            return dict(p=self.pose.copy(), q=self.q.copy(), v=self.velocity.copy(),
                        age=time.monotonic()-min(self.pose_at,self.q_at))

    def command(self, command, *params):
        values = list(params)+[0]*(7-len(params))
        self.link.mav.command_long_send(self.system,self.component,command,0,*values)

    def send(self, velocity, yaw):
        if self.stream_thread is not None:
            with self.stream_lock:
                self.stream_command=(list(velocity),yaw,time.monotonic())
            return
        self._send(velocity,yaw)

    def start_stream(self,yaw):
        self.stream_command=([0,0,0],yaw,time.monotonic())
        def pump():
            while not self.stream_stop.is_set():
                started=time.monotonic()
                with self.stream_lock:
                    velocity,angle,updated=self.stream_command
                # 主循环阻塞也持续发送；超过300ms没有更新则只允许零速度。
                self._send(velocity if started-updated<.3 else [0,0,0],angle)
                self.stream_stop.wait(max(0,.02-(time.monotonic()-started)))
        self.stream_thread=threading.Thread(target=pump,daemon=True)
        self.stream_thread.start()

    def close(self):
        self.stream_stop.set()
        if self.stream_thread:self.stream_thread.join(timeout=1)
        self.link.close()

    def _send(self, velocity, yaw):
        now = time.monotonic()
        if now-self.last_hb > 1:
            self.link.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,0,0,mavutil.mavlink.MAV_STATE_ACTIVE)
            self.last_hb = now
        # position/acceleration/yaw-rate ignored；NED velocity + yaw。
        self.link.mav.set_position_target_local_ned_send(0,self.system,self.component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED,7|448|2048,0,0,0,
            *map(float,velocity),0,0,0,float(yaw),0)

    def hold(self):
        self.command(mavutil.mavlink.MAV_CMD_DO_SET_MODE,1,4,3)


class Vision:
    def __init__(self, config, flight, actor, output, plan=None):
        self.config, self.flight, self.actor, self.output = config, flight, actor, output
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.latest = None
        self.confirmed = False
        self.error = None
        self.plan=plan
        self.valid_follow_s=0.
        self.history = deque(maxlen=20)
        self.filtered_velocity = np.zeros(3)
        self.dino = DinoClient(config['DINO_DETECT_URL'],timeout=3)
        self.model = calibration()
        self.thread = threading.Thread(target=self.worker,daemon=True)
        self.thread.start()

    def read(self):
        with self.lock:
            return self.latest.copy() if self.latest else None

    def worker(self):
        next_dino = next_voxels = 0
        voxels = None
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                rgb, depth = paired_frames(self.config['STAGE5_RGB_URL'],self.config['STAGE5_DEPTH_URL'],1,.05)
                own = self.flight.snapshot()
                target = target_surface(rgb,depth,self.model)
                if own is None or own['age'] > .3:
                    time.sleep(.05)
                    continue
                if started >= next_dino:
                    image, _ = camera_png('',1,rgb)
                    response, latency = self.dino.detect(image,text=self.plan['stages'][0]['dino_text'] if self.plan else 'a red car. a red box.')
                    for candidate in response['detections']:
                        if target:
                            a=target['box_xyxy']; b=candidate['box_xyxy']
                            ix=max(0,min(a[2],b[2])-max(a[0],b[0])); iy=max(0,min(a[3],b[3])-max(a[1],b[1]))
                            if ix*iy/((a[2]-a[0])*(a[3]-a[1])) > .5 and candidate['score'] > .2:
                                self.confirmed = True
                                target['semantic_label'],target['semantic_score'] = candidate['label'],candidate['score']
                    (self.output/'latest_detection.json').write_text(json.dumps(response,indent=2))
                    (self.output/'latest_rgb.png').write_bytes(image)
                    next_dino = time.monotonic()+3
                if not self.confirmed or target is None:
                    with self.lock:
                        self.latest = None
                    time.sleep(.1)
                    continue
                camera = np.array(target['position_camera_flu_m'])
                world = camera_to_ned(camera,own)
                stamp = rgb[0]['sim_time']
                self.history.append((stamp,world))
                if len(self.history) >= 5 and stamp-self.history[0][0] > .4:
                    ts=np.array([t for t,p in self.history]); ps=np.array([p for t,p in self.history])
                    centered=ts-ts.mean(); velocity=(centered[:,None]*(ps-ps.mean(axis=0))).sum(axis=0)/(centered@centered)
                    velocity[2]=0
                    if np.linalg.norm(velocity) < 2.5:
                        self.filtered_velocity=.8*self.filtered_velocity+.2*velocity
                clearance=forward_clearance(depth,self.model)
                if started >= next_voxels:
                    voxels=build(depth[0],depth[1],self.model)
                    next_voxels=time.monotonic()+1
                    (self.output/'latest_voxels.json').write_text(json.dumps(voxels,indent=2))
                observation=dict(target=target, target_ned=world.tolist(), velocity_ned=self.filtered_velocity.tolist(),
                    at=rgb[0]['received'], sim_time=stamp, clearance_m=clearance, confirmed=self.confirmed)
                with self.lock:
                    self.latest=observation
                candidates=dict(voxels['motion_candidates'])
                candidates['forward_1m']=dict(candidates['forward_1m'],
                    execution_policy='cautious' if clearance > 1.5 and candidates['forward_1m']['status'] != 'blocked' else 'stop')
                state=dict(mission='跟随已确认红色车尾后方，水平间距8米，上方2米。',
                    observed=dict(target_candidates=[target], target_response_source='http_and_color_tracking',
                        local_space=dict(motion_candidates=candidates,front_clearance_m=clearance),
                        tracking=observation, distance_horizontal_m=float(np.linalg.norm(camera[:2])),
                        height_above_surface_m=float(-camera[2]),
                        target_motion_direction='estimated from RGBD history; initially use camera forward',
                        simulation_policy='unknown near camera frustum retained; max 1.2 m/s cautious following, blocked veto'),
                    execution_mode='simulation_follow')
                if self.plan:
                    state.update(mission=self.plan['mission'],plan_version=self.plan['version'],
                        stage=self.plan['stages'][0],progress={'valid_follow_s':self.valid_follow_s})
                (self.output/'latest_jev_state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
                self.actor.offer(state,rgb[0]['received'])
            except Exception as exc:
                self.error=type(exc).__name__
            self.stop.wait(max(.02,.1-(time.monotonic()-started)))

    def close(self):
        self.stop.set(); self.thread.join(timeout=4)


def target_command(speed):
    subprocess.run(['docker','exec','uav-stage5-gazebo','python3','/scene/target_command.py',
        '--speed',str(speed)],check=True,stdout=subprocess.DEVNULL,timeout=4)


def allow_follow(judgment, observation):
    risk=judgment.get('risk')
    return bool(observation and observation.get('confirmed') and judgment.get('actionable')
        and judgment.get('effective_maneuver')=='hold_course' and risk is not None and risk < 1.7
        and observation['clearance_m'] > 1.5)


def decision_error(judgment):
    if judgment.get('source')=='error':
        detail=f"Jev调用失败：{judgment.get('error_type')} HTTP={judgment.get('error_http_status')} category={judgment.get('error_category')} {judgment.get('error_message','')}"
        if judgment.get('error_http_status')==451:
            detail+='；检查 stage5/.env 的 JEV_PROXY 与服务支持地区'
        return detail
    return None


def main():
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=60)
    parser.add_argument('--target-speed',type=float,default=.7)
    parser.add_argument('--jev-budget',type=int,default=40)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--plan',type=Path,help='Qwen 生成并已校验的单阶段计划')
    args=parser.parse_args()
    try:plan=validate_plan(json.loads(args.plan.read_text()),args.seconds) if args.plan else None
    except (OSError,ValueError) as exc:parser.error(str(exc))
    stage=plan['stages'][0] if plan else None
    distance=stage['horizontal_distance_m'] if stage else 8
    above=stage['above_m'] if stage else 2
    if not 5<=args.seconds<=600 or not .1<=args.target_speed<=1 or not 1<=args.jev_budget<=200:
        parser.error('seconds 5～600；target-speed 0.1～1；jev-budget 1～200')
    lease=open('/tmp/uav-stage5-follow.lock','a+')
    try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('已有 Stage 5 跟随进程，拒绝争用 PX4')
    lease.seek(0);lease.truncate();lease.write(str(os.getpid()));lease.flush()
    output=args.output or Path(tempfile.mkdtemp(prefix='stage5-follow-'))
    if args.output:output.mkdir(parents=True,exist_ok=False)
    config=configuration()
    config.update(JEV_CALL_HZ='.5',JEV_CALL_BUDGET=str(args.jev_budget),JEV_STALE_AFTER_S='3')
    flight=actor=vision=None
    records=[]
    outcome='incomplete'
    end_reason=None
    stage_status='running' if plan else None
    try:
        flight=Flight('udpin:127.0.0.1:14545')
        if not flight.armed:raise RuntimeError('请先 scene.py takeoff 并等待悬停')
        if plan:(output/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
        actor=Tactician(config,question_set=follow_questions(stage))
        vision=Vision(config,flight,actor,output,plan)
        initial=flight.snapshot()['p']
        r=rotation(flight.snapshot()['q']); heading=r[:2,0]; heading/=np.linalg.norm(heading)
        yaw=math.atan2(heading[1],heading[0])
        flight.start_stream(yaw)
        started=time.monotonic()
        while time.monotonic()-started<2:
            flight.poll();flight.send([0,0,0],yaw);time.sleep(.02)
        deadline=time.monotonic()+15
        while not vision.read():
            flight.poll();flight.send([0,0,0],yaw)
            if time.monotonic()>deadline:raise RuntimeError(f'DINO/RGBD 目标锁定超时，视觉错误={vision.error}')
            time.sleep(.02)
        # 先确认决策服务可用，再进入执行并启动车辆，不能把 API 错误冒充 brake。
        print('等待首个有效 Jev 跟随决策；车辆保持停止',flush=True)
        target_command(0)
        deadline=time.monotonic()+15
        last_startup_error=0
        while not allow_follow(actor.read(),vision.read()):
            flight.poll();flight.send([0,0,0],yaw)
            decision=actor.read()
            error=decision_error(decision)
            if error and decision.get('terminal_error',True):raise RuntimeError(error+'；未启动车辆')
            if error and decision.get('consecutive_errors',0)!=last_startup_error:
                print(error+'；车辆保持停止，等待重试',flush=True)
                last_startup_error=decision['consecutive_errors']
            if time.monotonic()>deadline:
                raise RuntimeError(f"Jev尚未允许跟随：source={decision.get('source')} maneuver={decision.get('maneuver')}；未启动车辆")
            time.sleep(.02)
        flight.command(mavutil.mavlink.MAV_CMD_DO_SET_MODE,1,6)
        deadline=time.monotonic()+5
        while flight.mode!=6:
            flight.poll();flight.send([0,0,0],yaw)
            if time.monotonic()>deadline:raise RuntimeError('PX4 Offboard 切换失败')
            time.sleep(.02)
        target_command(args.target_speed)
        print(f'FOLLOW RUNNING: {output}',flush=True)
        started=last_log=last_print=time.monotonic()
        last_seen=started
        commanded=np.zeros(3)
        recovery_since=None
        car_paused=False
        previous_tick=started
        while time.monotonic()-started<args.seconds+(15 if plan else 0):
            tick=time.monotonic();flight.poll();own=flight.snapshot();obs=vision.read();judgment=actor.read()
            if plan and judgment.get('source')=='jev' and not judgment['stale']:
                stage_status=judgment['stage_status']
                if stage_status=='needs_replan':raise RuntimeError('Jev 请求重新规划；初版停止并保存现场，不自动编造下一阶段')
                if stage_status=='completed':
                    if vision.valid_follow_s<stage['duration_s']:
                        raise RuntimeError('Jev 提前宣布完成，累计有效跟随时间不满足计划；停止执行')
                    print('Jev确认当前stage已完成',flush=True)
                    break
            if plan and allow_follow(judgment,obs) and obs and tick-obs['at']<.7:
                vision.valid_follow_s+=min(.1,tick-previous_tick)
            previous_tick=tick
            error=decision_error(judgment)
            if error and judgment.get('terminal_error',True):raise RuntimeError(error+'；停车并悬停')
            if error or judgment.get('stale'):
                commanded[:]=0
                flight.send(commanded,yaw)
                if recovery_since is None:
                    recovery_since=tick
                    print((error or 'Jev决策过期')+'；停车悬停，等待服务恢复',flush=True)
                if not car_paused:
                    target_command(0);car_paused=True
            elif allow_follow(judgment,obs) and obs and tick-obs['at']<.7:
                if car_paused:
                    target_command(args.target_speed);car_paused=False
                    print('Jev已恢复有效决策；继续跟随',flush=True)
                recovery_since=None
            if recovery_since is not None and tick-recovery_since>15:
                raise RuntimeError('Jev恢复等待超过15秒；结束跟随')
            if own['age']>.5 or tick-flight.heartbeat_at>3:raise RuntimeError('PX4 telemetry stale')
            if flight.mode != 6 or not flight.armed:raise RuntimeError('PX4 Offboard/arming state lost')
            if not np.isfinite(own['p']).all() or not np.isfinite(own['q']).all():raise RuntimeError('PX4 estimate invalid')
            if np.linalg.norm(own['p'][:2]-initial[:2])>65 or not -6<own['p'][2]<-1:
                raise RuntimeError('飞行边界越界')
            desired=np.zeros(3);goal=None
            if obs and tick-obs['at']<.7:
                last_seen=tick
                point=np.array(obs['target_ned']);speed=np.array(obs['velocity_ned'])
                if np.linalg.norm(speed[:2])>.25:
                    direction=speed[:2]/np.linalg.norm(speed[:2]);heading=.9*heading+.1*direction;heading/=np.linalg.norm(heading)
                age=tick-obs['at'];point+=speed*min(age,.5)
                goal=point.copy();goal[:2]-=distance*heading;goal[2]-=above
                delta=point-own['p'];yaw=math.atan2(delta[1],delta[0])
                if allow_follow(judgment,obs):
                    desired=speed+np.array([.65,.65,.8])*(goal-own['p'])
                    length=np.linalg.norm(desired[:2])
                    if length>1.2:desired[:2]*=1.2/length
                    desired[2]=np.clip(desired[2],-.5,.5)
            if tick-last_seen>4:raise RuntimeError('目标跟踪持续丢失')
            # 速度变化率限制；失效/刹停也保持流，不阻塞 Offboard 心跳。
            commanded+=np.clip(desired-commanded,-.04,.04)
            flight.send(commanded,yaw)
            if tick-last_log>.2:
                row=dict(t=tick-started,own_ned=own['p'].tolist(),v_ned=commanded.tolist(),
                    target=obs,goal_ned=goal.tolist() if goal is not None else None,judgment=judgment,
                    mode=flight.mode)
                records.append(row);last_log=tick
            if tick-last_print>3:
                print(json.dumps(dict(t=round(tick-started,1),maneuver=judgment['maneuver'],
                    source=judgment['source'],fresh=judgment['source']=='jev' and not judgment['stale'],
                    stage_status=judgment.get('stage_status'),
                    effective_maneuver=judgment.get('effective_maneuver'),velocity=commanded.round(2).tolist(),
                    target_range=round(obs['target']['range_m'],2) if obs else None)),flush=True)
                last_print=tick
            if actor.attempts>=actor.budget and judgment['stale']:raise RuntimeError('Jev预算已耗尽，停止跟随')
            time.sleep(max(0,.02-(time.monotonic()-tick)))
        if plan and stage_status!='completed':raise RuntimeError('等待Jev确认阶段完成超时；不标记任务完成')
        outcome='completed'
    except RuntimeError as exc:
        outcome='failed';end_reason=str(exc)
        print(f'跟随停止：{end_reason}',flush=True)
        return 1
    except KeyboardInterrupt:
        outcome='interrupted';end_reason='user_interrupt'
        print('跟随已中断；停车并悬停',flush=True)
        return 130
    finally:
        if flight:
            try:target_command(0)
            except (OSError,subprocess.SubprocessError):print('停车请求失败，继续发送 PX4 停止指令',flush=True)
            try:
                for _ in range(10):flight.send([0,0,0],locals().get('yaw',0));time.sleep(.02)
                flight.hold()
            finally:flight.close()
        if vision:vision.close()
        if actor:
            stats=actor.stats();(output/'jev_stats.json').write_text(json.dumps(stats,indent=2))
        (output/'flight.json').write_text(json.dumps(records,ensure_ascii=False,indent=2,allow_nan=False))
        (output/'run.json').write_text(json.dumps(dict(outcome=outcome,seconds=args.seconds,
            end_reason=end_reason,
            target_speed_mps=args.target_speed,horizontal_distance_from_rear_m=distance,above_rear_m=above,
            stage_status=stage_status,valid_follow_s=vision.valid_follow_s if vision else 0,
            perception='DINO semantic confirmation + red RGB appearance + depth',
            control='Jev gates geometry feedback through PX4 MAVLink Offboard',
            vehicle_truth_used_for_control=False,unknown_policy='simulation-only cautious speed <=1.2m/s'),indent=2))
        lease.close()
        print(f'Flight evidence: {output}',flush=True)


if __name__=='__main__':raise SystemExit(main())
