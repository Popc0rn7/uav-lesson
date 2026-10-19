"""持续感知与跨阶段PX4控制；模型线程不拥有飞行接口。"""
from collections import deque
import copy
import base64
import fcntl
import json
import math
from pathlib import Path
import statistics
import threading
import time

import numpy as np

from dino_client import camera_png, paired_frames, DinoClient
from depth_fusion import calibration, fuse
from follow import (Flight, rotation, target_surface, camera_to_ned, forward_clearance,
                    allow_follow, target_command, follow_questions)
from tactics import Tactician
from agent_errors import FatalControl
from evidence import write_json as dump
from latency import record as record_latency
from target_filter import filter_candidates
from planning_hints import JEV_INTERVAL_S, HORIZONTAL_SPEED_MPS, VERTICAL_SPEED_MPS
from voxel_scene import build


class Perception:
    """丢失目标也发布事实；配置版本改变后丢弃旧检测响应。"""
    def __init__(self, config, flight, output=None):
        self.config, self.flight = config, flight
        self.output = output; self.dino_pending = False
        self.filter_threshold = float(config.get('DINO_MIN_SCORE', '.7' if config.get('STAGE5_BACKEND') == 'airsim' else '.35'))
        if not 0 <= self.filter_threshold <= 1:
            raise ValueError('DINO_MIN_SCORE 必须为0～1')
        self.lock = threading.Lock(); self.stop = threading.Event()
        self.generation = 0; self.text = 'a red car. a red box.'
        self.latest = {}; self.frame = None; self.error = None; self.last_seen = None
        self.model = config.get('CAMERA_MODEL') or calibration(); self.dino = DinoClient(config['DINO_DETECT_URL'], timeout=3)
        self.history = deque(maxlen=20); self.velocity = np.zeros(3)
        self.thread = threading.Thread(target=self.worker, daemon=True); self.thread.start()

    def configure(self, text):
        with self.lock:
            self.generation += 1; self.text = text
            self.latest = {}  # 禁止将旧配置的确认结果授权给新阶段。
            return self.generation

    def snapshot(self):
        with self.lock:
            value = copy.deepcopy(self.latest)
            value['perception_error'] = self.error
            value['lost_for_s'] = None if self.last_seen is None else time.monotonic() - self.last_seen
            return value

    def image(self):
        with self.lock: return dict(self.frame) if self.frame else None

    def publish_request_preview(self, rgb, depth, png, generation, detection=None):
        """仅在DINO实际送检时写网页快照；后台跟踪帧不做网页深度编码。"""
        if not self.output:
            return
        try:
            dm, raw = depth
            values = np.ndarray((dm['height'], dm['width']), dtype='<f4', buffer=raw,
                                strides=(dm['step'], 4))
            valid = np.isfinite(values) & (values > 0) & (values <= 20)
            t = np.clip(np.nan_to_num(values, nan=0, posinf=20)/20, 0, 1)
            colors = np.stack((255*(1-t), 210*(1-np.abs(2*t-1)), 255*t), axis=-1).astype('uint8')
            colors[~valid] = 0
            meta = dict(width=dm['width'], height=dm['height'], step=dm['width']*3, format='RGB_INT8')
            depth_png, _ = camera_png('', 1, (meta, colors.tobytes()))
            preview = dict(received=rgb[0]['received'], sim_time=rgb[0]['sim_time'],
                rgb=base64.b64encode(png).decode(), depth=base64.b64encode(depth_png).decode(),
                source='dino_request', image_sent_to='dino', detection_received=rgb[0]['received'],
                detection=detection)
            with self.lock:
                if generation == self.generation:
                    dump(self.output/'preview.json', preview)
        except (OSError, ValueError, KeyError):
            pass

    def worker(self):
        seen_generation = -1; confirmed = False; next_dino = next_voxels = 0
        voxels = None; detections = []; candidate_audit = []; semantic = {}; fused_targets = []; detected_at = None
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                with self.lock: generation, text = self.generation, self.text
                if generation != seen_generation:
                    confirmed = False; next_dino = 0; seen_generation = generation; semantic = {}
                    fused_targets = []; detected_at = None; self.detection_preview = None
                rgb, depth = paired_frames(self.config['STAGE5_RGB_URL'], self.config['STAGE5_DEPTH_URL'], 1, .05)
                png, metadata = camera_png('', 1, rgb)
                target = target_surface(rgb, depth, self.model)
                if started >= next_dino:
                    self.dino_pending = True
                    try:
                        self.publish_request_preview(rgb, depth, png, generation)
                        response, _ = self.dino.detect(png, text=text)
                    finally:
                        self.dino_pending = False
                    detections, candidate_audit = filter_candidates(response['detections'], self.filter_threshold)
                    filtered_response = {**response, 'detections': detections}
                    fused_targets = fuse(filtered_response,rgb[0],depth[0],depth[1],self.model)['targets']
                    confirmed = False; semantic = {}
                    detected_at = rgb[0]['received']
                    for candidate in detections:
                        if target:
                            a, b = target['box_xyxy'], candidate['box_xyxy']
                            overlap = max(0, min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
                            if overlap/((a[2]-a[0])*(a[3]-a[1])) > .5 and candidate['score'] > .2:
                                confirmed = True
                                semantic = {'semantic_label': candidate['label'], 'semantic_score': candidate['score']}
                    self.detection_preview = dict(image=base64.b64encode(png).decode(),
                        detections=candidate_audit, width=response.get('width', rgb[0].get('width')), height=response.get('height', rgb[0].get('height')))
                    self.publish_request_preview(rgb, depth, png, generation, self.detection_preview)
                    next_dino = time.monotonic() + 3
                own = self.flight.snapshot()
                tracking = None
                if target and confirmed and own and own['age'] < .3:
                    target.update(semantic)
                    world = camera_to_ned(target['position_camera_flu_m'], own)
                    stamp = rgb[0]['sim_time']; self.history.append((stamp,world))
                    if len(self.history) >= 5 and stamp-self.history[0][0] > .4:
                        ts = np.array([t for t,p in self.history]); ps = np.array([p for t,p in self.history])
                        centered = ts-ts.mean()
                        velocity = (centered[:,None]*(ps-ps.mean(axis=0))).sum(axis=0)/(centered@centered)
                        velocity[2] = 0
                        if np.linalg.norm(velocity) < 2.5: self.velocity = .8*self.velocity+.2*velocity
                    tracking = dict(target=target, target_ned=world.tolist(), velocity_ned=self.velocity.tolist(),
                                    at=rgb[0]['received'], sim_time=stamp, confirmed=True,
                                    clearance_m=forward_clearance(depth,self.model))
                if started >= next_voxels or voxels is None:
                    voxels = build(depth[0],depth[1],self.model); next_voxels = time.monotonic()+1
                value = {'at': rgb[0]['received'], 'sim_time': rgb[0]['sim_time'], 'generation': generation,
                         'tracking': tracking, 'detections': detections, 'detection_candidates': candidate_audit,
                         'semantic_policy': 'DINO candidate + current RGBD overlap; no generic identity tracking',
                         'dino_text': text,
                         'semantic_targets': fused_targets, 'detection_received': detected_at,
                         'confirmed': tracking is not None, 'local_space': {
                             'motion_candidates': copy.deepcopy(voxels['motion_candidates']),
                             'front_clearance_m': forward_clearance(depth,self.model)}}
                with self.lock:
                    if generation == self.generation:
                        self.latest = value; self.error = None
                        if tracking: self.last_seen = time.monotonic()
                        self.frame = {'png': png, 'sim_time': metadata['sim_time'],
                                      'received': metadata['received'], 'generation': generation}
            except Exception as exc:
                with self.lock: self.error = type(exc).__name__
            self.stop.wait(max(.02, .1-(time.monotonic()-started)))

    def close(self):
        self.stop.set(); self.thread.join(timeout=.1)


class ReadOnlyRuntime:
    """plan-only没有飞行接口。"""
    def __init__(self, config): self.config = config; self.frame = None
    def service(self): pass
    def snapshot(self): return {'execution': 'plan_only'}
    def images(self):
        png, meta = camera_png(self.config['STAGE5_RGB_URL'], 2)
        self.frame = {'png': png, 'sim_time': meta['sim_time'], 'received': meta['received']}
        return [self.frame]
    def freeze(self): pass
    def close(self): pass


class FlightRuntime:
    def __init__(self, config, output, deadline, target_speed=.7, *, flight=None, lease=None, perception_class=None):
        self.config, self.output, self.deadline = config, Path(output), deadline
        self.target_speed = target_speed; self.car_started = False
        self.flight = self.perception = None; self.actor = None; self.active = False; self.frozen = False
        self.simulation_paused = False; self.resume_until = 0
        self.stop_requested = False; self.current = None; self.frames = []; self.rows = []
        self.lease = lease or open('/tmp/uav-stage5-follow.lock','a+')
        try:
            fcntl.flock(self.lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lease.close(); raise RuntimeError('已有 Stage 5 执行器，拒绝争用 PX4') from None
        try:
            self.flight = flight or Flight('udpin:127.0.0.1:14545', timeout=max(.01,min(10,deadline-time.monotonic())))
            if not self.flight.armed: raise FatalControl('请先 scene.py takeoff 并等待悬停')
            own = self.flight.snapshot(); self.initial = own['p'].copy()
            heading = rotation(own['q'])[:2,0]; self.heading = heading/np.linalg.norm(heading)
            self.yaw = math.atan2(self.heading[1],self.heading[0])
            self.flight.start_stream(self.yaw)
            self.perception = (perception_class or Perception)(config,self.flight,self.output)
        except BaseException:
            if self.flight: self.flight.close()
            self.lease.close(); raise

    def simulation_pause_changed(self, paused):
        self.simulation_paused = paused
        self.flight.send([0,0,0],self.yaw)
        if not paused:
            self.resume_until = time.monotonic()+2

    def service(self):
        if self.flight is None: return
        self.flight.poll()
        if self.frozen: return
        if self.simulation_paused:
            self.flight.send([0,0,0],self.yaw)
            return
        own = self.flight.snapshot()
        if own is None or own['age'] > .5 or time.monotonic()-self.flight.heartbeat_at > 3:
            if time.monotonic() < self.resume_until:
                self.flight.send([0,0,0],self.yaw)
                return
            self.freeze(); raise FatalControl('PX4 telemetry stale')
        if not self.flight.armed or not np.isfinite(own['p']).all() or not np.isfinite(own['q']).all():
            self.freeze(); raise FatalControl('PX4 arming/estimate invalid')
        altitude_outside = self.config.get('STAGE5_BACKEND') != 'airsim' and not -6 < own['p'][2] < -1
        horizontal_from_start = float(np.linalg.norm(own['p'][:2]-self.initial[:2]))
        if self.config.get('STAGE5_BACKEND') != 'airsim' and (horizontal_from_start > 65 or altitude_outside):
            self.freeze()
            raise FatalControl(f'飞行边界越界: horizontal_from_start_m={horizontal_from_start:.3f}, '
                               f'limit_m=65, ned_z_m={own["p"][2]:.6f}, '
                               f'allowed_ned_z_m={"unrestricted" if self.config.get("STAGE5_BACKEND") == "airsim" else "(-6, -1)"}')
        if self.active and self.offboard_seen and self.flight.mode != 6:
            self.freeze(); raise FatalControl('PX4 Offboard state lost')
        if not self.active: self.flight.send([0,0,0],self.yaw)

    def snapshot(self):
        value = self.perception.snapshot() if self.perception else {}
        if value.get('at') is not None: value['age_s'] = time.monotonic()-value['at']
        if value.get('detection_received') is not None:
            value['detection_age_s'] = time.monotonic()-value['detection_received']
        value['vehicle_truth_used'] = False
        if self.config.get('STAGE5_BACKEND') == 'airsim':
            value.update(horizontal_speed_limit_mps=3., vertical_speed_limit_mps=1.)
        if self.config.get('STAGE5_BACKEND') == 'airsim':
            value.update(active_search_available=True, search_description='optional stationary yaw at20deg/s; Qwen stage instructions and Jev decisions govern its use')
        own = self.flight.snapshot() if self.flight else None
        if own is not None:
            value['own_position_ned_m'] = own['p'].tolist()
        return value

    def ui_snapshot(self):
        observation = self.snapshot()
        return dict(active=self.active, frozen=self.frozen, simulation_paused=self.simulation_paused, observation=observation,
                    stage=self.current, tag=getattr(self, 'tag', {}),
                    progress=dict(getattr(self, 'progress', {})),
                    judgment=self.actor.read() if self.actor else {},
                    jev_pending=self.actor.pending if self.actor else False,
                    jev_stats=self.actor.stats() if self.actor else {},
                    dino_pending=getattr(self.perception, 'dino_pending', False),
                    block_reason=getattr(self, 'block_reason', None),
                    rejected_stage_status=getattr(self, 'rejected_stage_status', None),
                    mode=self.flight.mode if self.flight else None,
                    velocity_ned=getattr(self, 'commanded', np.zeros(3)).tolist(),
                    row=self.rows[-1] if self.rows else None)

    def images(self):
        result = list(self.frames)
        frame = self.perception.image() if self.perception else None
        if frame and not any(f.get('sim_time') == frame.get('sim_time') for f in result): result.append(frame)
        if not result:
            png, meta = camera_png(self.config['STAGE5_RGB_URL'], 2)
            result = [{'png': png, 'sim_time': meta['sim_time'], 'received': meta['received']}]
        if len(result) > 4: result = [result[0],result[len(result)//2],result[-2],result[-1]]
        return result

    def start(self, stage, progress, tag, directory):
        if self.frozen: raise FatalControl('execution frozen')
        if stage['skill'] == 'follow_vehicle' and self.config.get('STAGE5_BACKEND') != 'airsim':
            raise ValueError('follow_vehicle 需要 AirSim 执行后端')
        if self.config.get('STAGE5_BACKEND') == 'airsim' and stage['skill'] == 'follow_red_vehicle':
            raise ValueError('AirSim 后端不提供红色专用跟踪')
        if any(v in stage['allowed_skills'] for v in ('scan_yaw', 'approach_target')) and self.config.get('STAGE5_BACKEND') != 'airsim':
            raise ValueError('scan_yaw 只在AirSim后端实现')
        self.current, self.progress, self.tag, self.directory = stage, progress, tag, Path(directory)
        self.progress.setdefault('enabled_follow_s',0.)
        self.rows = []; self.frames = []; self.stats_samples = []; self.last_row = self.last_print = 0
        self.last_frame = 0
        self.started = self.last_tick = time.monotonic(); self.commanded = np.zeros(3)
        self.no_tracking_since = self.no_decision_since = None
        self.block_reason = None; self.rejected_stage_status = None
        airsim = self.config.get('STAGE5_BACKEND') == 'airsim'
        self.offboard_seen = bool(airsim and self.flight.mode == 6); self.last_mode_request = 0
        self.visual_heading_initialized = False
        self.search_enabled = self.config.get('STAGE5_BACKEND') == 'airsim' and 'scan_yaw' in stage['allowed_skills']
        self.search_elapsed_s = 0.; self.search_active = False
        if self.search_enabled:
            from stage5.airsim.yaw_search import YawScan
            self.search_scan = YawScan(self.yaw)
        self.hold_confirmed = airsim; self.mode_requested_at = None
        self.flight.send([0,0,0],self.yaw)
        if not airsim: self.flight.hold()
        self.hold_requested_at = time.monotonic()
        self.active = True
        self.generation = self.perception.configure(stage['dino_text'])
        config = {**self.config, 'JEV_CALL_HZ': str(1/JEV_INTERVAL_S), 'JEV_CALL_BUDGET': str(stage['allocation']['budget']),
                  'JEV_STALE_AFTER_S': '3', 'LATENCY_OUTPUT': str(self.output), 'JEV_REQUEST_LOG_DIR': str(self.directory)}
        self.actor = Tactician(config, question_set=follow_questions(stage, simple=True))
        if not self.car_started and self.config.get('STAGE5_BACKEND') != 'airsim':
            target_command(self.target_speed); self.car_started = True
        dump(self.directory/'stage.json', {'stage': stage, **tag})
        print(f"STAGE START {tag['stage_id']} attempt={tag['attempt']} allocation={stage['allocation']}",flush=True)

    def step(self, continuing=False):
        now = time.monotonic(); own = self.flight.snapshot(); observation = self.snapshot()
        wall_delta = max(0., now-self.last_tick)
        delta = min(.1,wall_delta); self.last_tick = now
        if now-self.started >= self.current['allocation']['timeout']:
            return {'status':'timeout','reason':'stage_timeout'}
        if not self.offboard_seen:
            self.flight.send([0,0,0],self.yaw)
            if now-self.started > 5: raise FatalControl('PX4 Hold/Offboard 切换失败')
            if not self.hold_confirmed:
                if self.flight.mode == 4 and self.flight.heartbeat_at > self.hold_requested_at:
                    self.hold_confirmed = True
                return None
            if (self.mode_requested_at is not None and self.flight.mode == 6
                    and self.flight.heartbeat_at > self.mode_requested_at):
                self.offboard_seen = True
            elif now-self.last_mode_request > .5:
                self.flight.command(176,1,6); self.last_mode_request = now
                if self.mode_requested_at is None: self.mode_requested_at = now
            return None
        tracking = observation.get('tracking')
        fresh_limit = 1. if self.config.get('STAGE5_BACKEND') == 'airsim' else .7
        fresh = observation.get('generation') == self.generation and now-observation.get('at',0) < fresh_limit
        if not fresh: tracking = None
        candidates = copy.deepcopy(observation.get('local_space',{}).get('motion_candidates',{}))
        forward = candidates.get('forward_1m',{'status':'unknown'})
        space_clearance = observation.get('local_space',{}).get('front_clearance_m')
        clearance = space_clearance if space_clearance is not None else 0
        forward['execution_policy'] = 'cautious' if clearance > 1.5 and forward['status'] != 'blocked' else 'stop'
        candidates['forward_1m'] = forward
        state = dict(mission=self.current['goal'],stage=self.current,progress=dict(self.progress),**self.tag,
            observed=dict(capture_received_monotonic=observation.get('at'), target_candidates=observation.get('semantic_targets',[]),
                target_response_source=('dino_rgbd_current_frame' if self.config.get('STAGE5_BACKEND') == 'airsim' else 'http_and_color_tracking'), local_space=dict(motion_candidates=candidates,
                    front_clearance_m=clearance),tracking=tracking,observation_age_s=now-observation.get('at',now),
                lost_for_s=observation.get('lost_for_s'),perception_error=observation.get('perception_error'),
                detection_age_s=observation.get('detection_age_s'),
                target_visible=bool(observation.get('detections')) if self.config.get('STAGE5_BACKEND') == 'airsim' else tracking is not None,
                target_selection=observation.get('target_selection'),
                target_memory=observation.get('target_memory')),execution_mode='simulation_follow')
        # 空候选仍提交；时间戳采用本次事实整理时间，传感器年龄另行明确提供。
        if tracking:
            self.no_tracking_since = None
        elif self.no_tracking_since is None:
            self.no_tracking_since = now
        unavailable_s = 0 if self.no_tracking_since is None else now-self.no_tracking_since
        search_enabled = getattr(self, 'search_enabled', False)
        search_available = search_enabled
        lost_timeout = None if self.config.get('STAGE5_BACKEND') == 'airsim' else 8.
        state['execution_health'] = dict(no_tracking_for_s=unavailable_s,
            active_search_available=search_enabled, recovery='stationary_scan_yaw' if search_enabled else 'stationary_wait_only',
            yaw_action_available=search_available,
            search_elapsed_s=getattr(self, 'search_elapsed_s', 0.),
            search_travel_deg=math.degrees(self.search_scan.travel) if search_enabled else 0.,
            previous_rejected_judgment=getattr(self,'rejected_stage_status',None),
            failure_facts=dict(tracking_lost=(not bool(tracking) if lost_timeout is None else unavailable_s >= lost_timeout),
                               blocked=(space_clearance is not None and 0 < space_clearance <= 1.5) or forward.get('status') == 'blocked'),
            latest_goal_errors=self.stats_samples[-1] if self.stats_samples else None,
            progress_note=('continuous follow: valid_follow_s is diagnostic, not a completion timer' if self.current.get('continuous') else 'valid_follow_s=0 while approaching is normal; error alone is not failure'),
            control_state=dict(approach_standoff_m=self.current.get('horizontal_distance_m',8.),
                horizontal_target_distance_m=(float(np.linalg.norm(np.array(tracking['target_ned'])[:2]-own['p'][:2])) if tracking else None),
                follow_direction_available=bool(tracking and tracking.get('direction_confirmed')),
                note='In follow_vehicle, approach_target and hold_course both enable relative goal control when measured motion geometry is available; before that, horizontal approach holds altitude. Unknown path with cautious policy is permitted, not known blockage.'),
            stage_elapsed_s=now-self.started,
            stage_remaining_s=max(0, self.current['allocation']['timeout']-(now-self.started)),
            no_tracking_timeout_s=lost_timeout,
            note='语义检测不等于可执行跟踪，无距离不平移。偏航遵循Qwen当前stage语言指示和Jev决策；圈数和目标出现不自动结束动作。图像/决策失效保持。')
        self.actor.offer(state,now)
        judgment = self.actor.read()
        matching = all(judgment.get(k) == v for k,v in self.tag.items())
        usable = matching and judgment['source'] == 'jev' and not judgment['stale']
        status = judgment.get('stage_status') if usable else 'running'
        if continuing and status == 'done':
            # 验收只延后阶段切换，不复用旧速度；继续执行本次判断的合法动作。
            status = 'running'
            allowed = judgment.get('motion_path_allowed', False)
            judgment.update(actionable=usable and allowed,
                            effective_maneuver=judgment.get('maneuver') if allowed else 'brake',
                            guard_reason=None if allowed else 'candidate path blocked or unknown')
        self.rejected_stage_status = None
        reason = judgment.get('stage_reason')
        decision_evidence = judgment.get('decision_evidence', {})
        if status == 'failed' and reason is not None and self.config.get('STAGE5_BACKEND') != 'airsim':
            supported = decision_evidence.get('failure_facts', {}).get(reason, False)
            if not supported:
                self.rejected_stage_status = dict(status=status, reason=reason, rejected='no supporting failure fact')
                status = 'running'  # 保留原始failed、不授权运动，等待新判断；不接受阶段。
        if status == 'done' and self.config.get('STAGE5_BACKEND') != 'airsim':
            sufficient = (decision_evidence.get('valid_follow_s', 0) >= self.current['duration_s']
                          if self.current['skill'] in ('follow_red_vehicle', 'follow_vehicle') else
                          decision_evidence.get('tracking_confirmed', False))
            if not sufficient:
                self.rejected_stage_status = dict(status='done',reason=reason,rejected='completion evidence not met')
                status = 'running'
        if status in ('done','failed'):
            return {'status':status,'reason':'jev_'+status,'judgment':judgment}
        if judgment['source'] == 'error' and judgment.get('terminal_error'):
            return {'status':'failed','reason':'jev_unavailable','judgment':judgment}
        if self.actor.attempts >= self.actor.budget and not self.actor.pending:
            return {'status':'budget_exhausted','reason':'jev_budget_exhausted','judgment':judgment}
        if usable:
            self.no_decision_since = None
        elif self.no_decision_since is None:
            self.no_decision_since = now
        self.block_reason = ('target_tracking_unavailable' if not tracking else
                             'jev_error' if judgment['source'] == 'error' else
                             'jev_decision_unavailable' if not usable else
                             judgment.get('guard_reason') or
                             ('jev_'+judgment.get('maneuver', 'waiting') if judgment.get('effective_maneuver') != 'hold_course' else None))
        if (lost_timeout is not None and unavailable_s >= lost_timeout):
            return {'status': 'failed', 'reason': 'tracking_unavailable', 'execution_health': state['execution_health'], 'judgment': judgment}
        if self.no_decision_since is not None and now-self.no_decision_since >= 15:
            return {'status': 'failed', 'reason': 'jev_decision_unavailable', 'judgment': judgment}
        horizontal_limit = 3. if self.config.get('STAGE5_BACKEND') == 'airsim' else HORIZONTAL_SPEED_MPS
        vertical_limit = 1. if self.config.get('STAGE5_BACKEND') == 'airsim' else VERTICAL_SPEED_MPS
        desired = np.zeros(3); goal = None
        if tracking:
            self.progress['observed_s'] += delta
            point = np.array(tracking['target_ned']); speed = np.array(tracking['velocity_ned'])
            d = point-own['p']; self.yaw = math.atan2(d[1],d[0])
            if np.linalg.norm(speed[:2]) > .25:
                direction = speed[:2]/np.linalg.norm(speed[:2])
                if self.current['skill'] == 'follow_vehicle' and not self.visual_heading_initialized:
                    self.heading = direction; self.visual_heading_initialized = True
                else:
                    self.heading = .9*self.heading+.1*direction
                self.heading /= np.linalg.norm(self.heading)
            if (self.current['skill'] in ('follow_red_vehicle', 'follow_vehicle') and not tracking.get('control_proxy')
                    and (self.current['skill'] != 'follow_vehicle' or tracking.get('direction_confirmed'))):
                if self.current['skill'] == 'follow_vehicle':
                    from stage5.airsim.geometry import follow_goal
                    goal = follow_goal(point, self.heading, self.current)
                else:
                    goal = point.copy(); goal[:2] -= self.current['horizontal_distance_m']*self.heading
                    goal[2] -= self.current['above_m']
                errors = goal-own['p']
                self.stats_samples.append({'horizontal_goal_error_m':float(np.linalg.norm(errors[:2])),
                                           'vertical_goal_error_m':float(abs(errors[2]))})
                direction_ready = self.current['skill'] != 'follow_vehicle' or tracking.get('direction_confirmed', False)
                if usable and direction_ready and judgment['maneuver'] in self.current['allowed_skills'] and (judgment.get('actionable') and judgment.get('effective_maneuver') in ('hold_course', 'approach_target')
                     if self.config.get('STAGE5_BACKEND') == 'airsim' else allow_follow(judgment,tracking)):
                    desired = speed+np.array([.65,.65,.8])*errors
                    norm = np.linalg.norm(desired[:2])
                    if norm > horizontal_limit: desired[:2] *= horizontal_limit/norm
                    desired[2] = np.clip(desired[2],-vertical_limit,vertical_limit)
                    self.progress['enabled_follow_s'] += delta
                    if np.linalg.norm(errors[:2]) <= 1. and abs(errors[2]) <= .5:
                        self.progress['valid_follow_s'] += delta
        if (tracking and tracking.get('confirmed') and usable and judgment.get('actionable')
                and (self.current['skill'] != 'follow_vehicle' or tracking.get('control_proxy') or not tracking.get('direction_confirmed'))
                and (judgment.get('effective_maneuver') == 'approach_target' or
                     self.config.get('STAGE5_BACKEND') == 'airsim' and judgment.get('effective_maneuver') == 'hold_course'
                     and (tracking.get('control_proxy') or not tracking.get('direction_confirmed')))
                and judgment.get('effective_maneuver') in self.current['allowed_skills']):
            horizontal = np.array(tracking['target_ned'])[:2]-own['p'][:2]
            norm = np.linalg.norm(horizontal)
            stand_off = self.current.get('horizontal_distance_m', 8.)
            if tracking.get('control_proxy') or norm > stand_off:
                desired[:2] = horizontal/max(norm, .1)*min(horizontal_limit, max(0., norm-stand_off))
            desired[2] = 0  # 代理不支持屋顶高度，接近期间保持当前高度。
            self.block_reason = 'approach_range_limit_proxy' if tracking.get('control_proxy') else 'approach_measured_target'
        if search_enabled:
            from stage5.airsim.yaw_search import yaw_of
            scan = (fresh and search_available and usable and judgment.get('actionable')
                    and judgment.get('effective_maneuver') == 'scan_yaw'
                    and not observation.get('perception_error'))
            if scan:
                self.yaw = self.search_scan.step(yaw_of(own), delta)
                self.search_elapsed_s += wall_delta
                self.block_reason = 'scan_yaw'
                desired[:] = 0; self.commanded[:] = 0
            else:
                if self.search_active and not tracking:
                    self.yaw = yaw_of(own)
                self.search_scan.pause(yaw_of(own))
            self.search_active = bool(scan)
        if not tracking or not usable or judgment.get('source') == 'error': self.commanded[:] = 0
        self.commanded += np.clip(desired-self.commanded,-.04,.04)
        command_started = time.monotonic()
        self.flight.send(self.commanded,self.yaw)
        if self.config.get('STAGE5_BACKEND') == 'airsim' and fresh and usable and now-self.last_row > .2:
            record_latency(self.output, 'command_submit', time.monotonic()-command_started, **self.tag)
            record_latency(self.output, 'capture_to_command', time.monotonic()-observation['at'], **self.tag)
        if now-self.last_row > .2:
            self.rows.append(dict(t=now-self.started,own_ned=own['p'].tolist(),v_ned=self.commanded.tolist(),
                yaw_command_rad=self.yaw, search_active=getattr(self, 'search_active', False),
                search_travel_deg=math.degrees(self.search_scan.travel) if search_enabled else 0.,
                target=tracking,goal_ned=goal.tolist() if goal is not None else None,judgment=judgment,
                progress=dict(self.progress),**self.tag))
            dump(self.directory/'latest_jev_state.json',state); self.last_row = now
        frame = self.perception.image()
        if frame and now-self.last_frame >= max(.5,self.current['allocation']['timeout']/32):
            self.frames.append(frame); self.last_frame = now
            if len(self.frames) > 34: del self.frames[1]
        if now-self.last_print > 3:
            print(json.dumps(dict(t=round(now-self.started,1),stage_id=self.tag['stage_id'],stage_status=status,
                maneuver=judgment.get('maneuver'),effective_maneuver=judgment.get('effective_maneuver'),
                block_reason=self.block_reason,source=judgment['source'],fresh=usable,
                velocity=self.commanded.round(2).tolist(),progress=self.progress),ensure_ascii=False),flush=True)
            self.last_print = now
        return None

    def end(self, result, keep_running=False):
        if not keep_running:
            self.active = False
            self.flight.send([0,0,0],self.yaw)
            if self.config.get('STAGE5_BACKEND') != 'airsim': self.flight.hold()
        if self.actor:
            if not keep_running: self.actor.close(wait=False)
            stats = self.actor.stats()
            if not keep_running: self.actor = None
        else: stats = {'attempts':0,'calls':0,'errors':0}
        metrics = {}
        if self.stats_samples:
            tail = self.stats_samples[len(self.stats_samples)//2:]
            for key in ('horizontal_goal_error_m','vertical_goal_error_m'):
                metrics['median_'+key] = statistics.median(r[key] for r in self.stats_samples)
                metrics['tail_median_'+key] = statistics.median(r[key] for r in tail)
                metrics['latest_'+key] = self.stats_samples[-1][key]
            metrics.update(valid_follow_horizontal_tolerance_m=1.,valid_follow_vertical_tolerance_m=.5)
        result = {**result, 'stage_elapsed_s':time.monotonic()-self.started,
                  'stage_allocation':self.current['allocation'],
                  'rejected_stage_status':getattr(self,'rejected_stage_status',None), 'jev_calls':stats['attempts'],'jev_successes':stats['calls'],
                  'jev_errors':stats['errors'],'elapsed_s':time.monotonic()-self.started,
                  'progress':dict(self.progress),'observation':self.snapshot(),
                  'metrics':metrics}
        dump(self.directory/'flight.json',self.rows)
        dump(self.directory/'jev_stats.json',stats)
        evidence = []
        for index, frame in enumerate(self.images()):
            path = self.directory/f'frame-{index}.png'; path.write_bytes(frame['png'])
            evidence.append({'path':str(path),**{k:v for k,v in frame.items() if k!='png'}})
        result['images'] = evidence
        return result

    def freeze(self):
        self.active = False; self.frozen = True
        if self.flight:
            self.flight.send([0,0,0],getattr(self,'yaw',0)); self.flight.hold()

    def close(self):
        try:
            self.freeze()
        finally:
            if self.actor: self.actor.close(wait=False)
            if self.perception: self.perception.close()
            if self.flight: self.flight.close()
            if self.car_started and self.config.get('STAGE5_BACKEND') != 'airsim':
                try: target_command(0)
                except Exception: pass
            self.lease.close()
