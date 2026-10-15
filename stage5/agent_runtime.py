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
from target_filter import filter_candidates
from planning_hints import JEV_INTERVAL_S, HORIZONTAL_SPEED_MPS, VERTICAL_SPEED_MPS
from voxel_scene import build


class Perception:
    """丢失目标也发布事实；配置版本改变后丢弃旧检测响应。"""
    def __init__(self, config, flight, output=None):
        self.config, self.flight = config, flight
        self.output = output; self.preview_at = 0; self.dino_pending = False
        self.filter_threshold = float(config.get('DINO_MIN_SCORE', '.35'))
        if not 0 <= self.filter_threshold <= 1:
            raise ValueError('DINO_MIN_SCORE 必须为0～1')
        self.lock = threading.Lock(); self.stop = threading.Event()
        self.generation = 0; self.text = 'a red car. a red box.'
        self.latest = {}; self.frame = None; self.error = None; self.last_seen = None
        self.model = calibration(); self.dino = DinoClient(config['DINO_DETECT_URL'], timeout=3)
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
                    next_dino = time.monotonic() + 3
                if self.output and time.monotonic()-self.preview_at > 1:
                    try:
                        # 独立感知线程编码图片，不占用飞行控制循环。
                        from dino_client import camera_png as encode_png
                        dm, raw = depth
                        values = np.ndarray((dm['height'], dm['width']), dtype='<f4', buffer=raw,
                                            strides=(dm['step'], 4))
                        valid = np.isfinite(values) & (values > 0) & (values <= 20)
                        t = np.clip(np.nan_to_num(values, nan=0, posinf=20)/20, 0, 1)
                        colors = np.stack((255*(1-t), 210*(1-np.abs(2*t-1)), 255*t), axis=-1).astype('uint8')
                        colors[~valid] = 0
                        meta = dict(width=dm['width'], height=dm['height'], step=dm['width']*3, format='RGB_INT8')
                        depth_png, _ = encode_png('', 1, (meta, colors.tobytes()))
                        preview = dict(received=rgb[0]['received'], sim_time=rgb[0]['sim_time'],
                            rgb=base64.b64encode(png).decode(), depth=base64.b64encode(depth_png).decode(),
                            detection_received=detected_at)
                        # 检测框只与提交 DINO 的同一帧显示。
                        preview['detection'] = getattr(self, 'detection_preview', None)
                        dump(self.output/'preview.json', preview)
                        self.preview_at = time.monotonic()
                    except (OSError, ValueError, KeyError):
                        pass
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
    def __init__(self, config, output, deadline, target_speed=.7):
        self.config, self.output, self.deadline = config, Path(output), deadline
        self.target_speed = target_speed; self.car_started = False
        self.flight = self.perception = None; self.actor = None; self.active = False; self.frozen = False
        self.simulation_paused = False; self.resume_until = 0
        self.stop_requested = False; self.current = None; self.frames = []; self.rows = []
        self.lease = open('/tmp/uav-stage5-follow.lock','a+')
        try:
            fcntl.flock(self.lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lease.close(); raise RuntimeError('已有 Stage 5 执行器，拒绝争用 PX4') from None
        try:
            self.flight = Flight('udpin:127.0.0.1:14545', timeout=max(.01,min(10,deadline-time.monotonic())))
            if not self.flight.armed: raise FatalControl('请先 scene.py takeoff 并等待悬停')
            own = self.flight.snapshot(); self.initial = own['p'].copy()
            heading = rotation(own['q'])[:2,0]; self.heading = heading/np.linalg.norm(heading)
            self.yaw = math.atan2(self.heading[1],self.heading[0])
            self.flight.start_stream(self.yaw)
            self.perception = Perception(config,self.flight,self.output)
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
        if np.linalg.norm(own['p'][:2]-self.initial[:2]) > 65 or not -6 < own['p'][2] < -1:
            self.freeze(); raise FatalControl('飞行边界越界')
        if self.active and self.offboard_seen and self.flight.mode != 6:
            self.freeze(); raise FatalControl('PX4 Offboard state lost')
        if not self.active: self.flight.send([0,0,0],self.yaw)

    def snapshot(self):
        value = self.perception.snapshot() if self.perception else {}
        if value.get('at') is not None: value['age_s'] = time.monotonic()-value['at']
        if value.get('detection_received') is not None:
            value['detection_age_s'] = time.monotonic()-value['detection_received']
        value['vehicle_truth_used'] = False
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
        self.current, self.progress, self.tag, self.directory = stage, progress, tag, Path(directory)
        self.progress.setdefault('enabled_follow_s',0.)
        self.rows = []; self.frames = []; self.stats_samples = []; self.last_row = self.last_print = 0
        self.last_frame = 0
        self.started = self.last_tick = time.monotonic(); self.commanded = np.zeros(3)
        self.no_tracking_since = self.no_decision_since = None
        self.block_reason = None; self.rejected_stage_status = None
        self.offboard_seen = False; self.last_mode_request = 0
        self.hold_confirmed = False; self.mode_requested_at = None
        self.flight.send([0,0,0],self.yaw); self.flight.hold()
        self.hold_requested_at = time.monotonic()
        self.active = True
        self.generation = self.perception.configure(stage['dino_text'])
        config = {**self.config, 'JEV_CALL_HZ': str(1/JEV_INTERVAL_S), 'JEV_CALL_BUDGET': str(stage['allocation']['budget']),
                  'JEV_STALE_AFTER_S': '3'}
        self.actor = Tactician(config, question_set=follow_questions(stage, simple=True))
        if not self.car_started:
            target_command(self.target_speed); self.car_started = True
        dump(self.directory/'stage.json', {'stage': stage, **tag})
        print(f"STAGE START {tag['stage_id']} attempt={tag['attempt']} allocation={stage['allocation']}",flush=True)

    def step(self):
        now = time.monotonic(); own = self.flight.snapshot(); observation = self.snapshot()
        delta = min(.1,now-self.last_tick); self.last_tick = now
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
        fresh = observation.get('generation') == self.generation and now-observation.get('at',0) < .7
        if not fresh: tracking = None
        candidates = copy.deepcopy(observation.get('local_space',{}).get('motion_candidates',{}))
        forward = candidates.get('forward_1m',{'status':'unknown'})
        space_clearance = observation.get('local_space',{}).get('front_clearance_m')
        clearance = space_clearance if space_clearance is not None else 0
        forward['execution_policy'] = 'cautious' if clearance > 1.5 and forward['status'] != 'blocked' else 'stop'
        candidates['forward_1m'] = forward
        state = dict(mission=self.current['goal'],stage=self.current,progress=dict(self.progress),**self.tag,
            observed=dict(target_candidates=observation.get('semantic_targets',[]),
                target_response_source='http_and_color_tracking', local_space=dict(motion_candidates=candidates,
                    front_clearance_m=clearance),tracking=tracking,observation_age_s=now-observation.get('at',now),
                lost_for_s=observation.get('lost_for_s'),perception_error=observation.get('perception_error'),
                detection_age_s=observation.get('detection_age_s'),
                target_visible=tracking is not None),execution_mode='simulation_follow')
        # 空候选仍提交；时间戳采用本次事实整理时间，传感器年龄另行明确提供。
        if tracking:
            self.no_tracking_since = None
        elif self.no_tracking_since is None:
            self.no_tracking_since = now
        unavailable_s = 0 if self.no_tracking_since is None else now-self.no_tracking_since
        state['execution_health'] = dict(no_tracking_for_s=unavailable_s,
            active_search_available=False, recovery='stationary_wait_only',
            previous_rejected_judgment=getattr(self,'rejected_stage_status',None),
            failure_facts=dict(tracking_lost=unavailable_s >= 8,
                               blocked=(space_clearance is not None and 0 < space_clearance <= 1.5) or forward.get('status') == 'blocked'),
            latest_goal_errors=self.stats_samples[-1] if self.stats_samples else None,
            progress_note='valid_follow_s=0 while approaching is normal; error alone is not failure',
            stage_elapsed_s=now-self.started,
            stage_remaining_s=max(0, self.current['allocation']['timeout']-(now-self.started)),
            no_tracking_timeout_s=8.,
            note='语义检测不等于可执行跟踪；too_far候选保留，但没有距离不能跟随。连续8秒无可用跟踪将结束本次stage并交Qwen验收。')
        self.actor.offer(state,now)
        judgment = self.actor.read()
        matching = all(judgment.get(k) == v for k,v in self.tag.items())
        usable = matching and judgment['source'] == 'jev' and not judgment['stale']
        status = judgment.get('stage_status') if usable else 'running'
        self.rejected_stage_status = None
        reason = judgment.get('stage_reason')
        if status == 'failed' and reason is not None:
            supported = state['execution_health']['failure_facts'].get(reason, False)
            if not supported:
                self.rejected_stage_status = dict(status=status, reason=reason, rejected='no supporting failure fact')
                status = 'running'  # 保留原始failed、不授权运动，等待新判断；不接受阶段。
        if status == 'done':
            sufficient = (self.progress['valid_follow_s'] >= self.current['duration_s']
                          if self.current['skill'] == 'follow_red_vehicle' else tracking is not None)
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
        if unavailable_s >= 8:
            return {'status': 'failed', 'reason': 'tracking_unavailable', 'execution_health': state['execution_health'], 'judgment': judgment}
        if self.no_decision_since is not None and now-self.no_decision_since >= 15:
            return {'status': 'failed', 'reason': 'jev_decision_unavailable', 'judgment': judgment}
        desired = np.zeros(3); goal = None
        if tracking:
            self.progress['observed_s'] += delta
            point = np.array(tracking['target_ned']); speed = np.array(tracking['velocity_ned'])
            d = point-own['p']; self.yaw = math.atan2(d[1],d[0])
            if np.linalg.norm(speed[:2]) > .25:
                direction = speed[:2]/np.linalg.norm(speed[:2]); self.heading = .9*self.heading+.1*direction
                self.heading /= np.linalg.norm(self.heading)
            if self.current['skill'] == 'follow_red_vehicle':
                goal = point.copy(); goal[:2] -= self.current['horizontal_distance_m']*self.heading
                goal[2] -= self.current['above_m']
                errors = goal-own['p']
                self.stats_samples.append({'horizontal_goal_error_m':float(np.linalg.norm(errors[:2])),
                                           'vertical_goal_error_m':float(abs(errors[2]))})
                if usable and judgment['maneuver'] in self.current['allowed_skills'] and allow_follow(judgment,tracking):
                    desired = speed+np.array([.65,.65,.8])*errors
                    norm = np.linalg.norm(desired[:2])
                    if norm > HORIZONTAL_SPEED_MPS: desired[:2] *= HORIZONTAL_SPEED_MPS/norm
                    desired[2] = np.clip(desired[2],-VERTICAL_SPEED_MPS,VERTICAL_SPEED_MPS)
                    self.progress['enabled_follow_s'] += delta
                    if np.linalg.norm(errors[:2]) <= 1. and abs(errors[2]) <= .5:
                        self.progress['valid_follow_s'] += delta
        if not tracking or not usable or judgment.get('source') == 'error': self.commanded[:] = 0
        self.commanded += np.clip(desired-self.commanded,-.04,.04)
        self.flight.send(self.commanded,self.yaw)
        if now-self.last_row > .2:
            self.rows.append(dict(t=now-self.started,own_ned=own['p'].tolist(),v_ned=self.commanded.tolist(),
                target=tracking,goal_ned=goal.tolist() if goal is not None else None,judgment=judgment,
                progress=dict(self.progress),**self.tag))
            dump(self.directory/'latest_jev_state.json',state); self.last_row = now
        frame = self.perception.image()
        if frame and now-self.last_frame >= max(.5,self.current['allocation']['timeout']/32):
            self.frames.append(frame); self.last_frame = now
            if len(self.frames) > 34: del self.frames[1]
        if now-self.last_print > 3:
            print(json.dumps(dict(t=round(now-self.started,1),stage_id=self.tag['stage_id'],stage_status=status,
                maneuver=judgment.get('maneuver'),source=judgment['source'],fresh=usable,
                velocity=self.commanded.round(2).tolist(),progress=self.progress),ensure_ascii=False),flush=True)
            self.last_print = now
        return None

    def end(self, result):
        self.active = False
        self.flight.send([0,0,0],self.yaw); self.flight.hold()
        if self.actor:
            self.actor.close(wait=False)
            stats = self.actor.stats(); self.actor = None
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
        self.freeze()
        if self.actor: self.actor.close(wait=False)
        if self.perception: self.perception.close()
        if self.flight: self.flight.close()
        if self.car_started:
            try: target_command(0)
            except Exception: pass
        self.lease.close()
