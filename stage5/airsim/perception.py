"""AirSim 候选跟踪：每帧重新 DINO/RGBD，不沿用红色掩膜或无限缓存身份。"""
import base64
from collections import deque
import json
import copy
import time

import numpy as np

from latency import record as record_latency
from agent_runtime import Perception
from depth_fusion import fuse
from dino_client import paired_frames, camera_png
from target_filter import filter_candidates
from voxel_scene import build
from stage5.airsim.geometry import camera_point_ned



def choose_target(targets):
    """当前帧最高分且有可用几何的候选；不做旧框身份锁定或分差否决。"""
    candidates = [v for v in targets if v['status'] in ('estimated_surface', 'too_far')]
    return max(candidates, key=lambda v: v['score'], default=None)


def control_point(target, model):
    """仅明确超量程使用光轴量程边界代理；不伪造深度测量。"""
    if target['status'] == 'estimated_surface':
        point = list(target['position_m'])
        box = target['depth_box_xyxy']
        point[2] = -(box[1]+.1*(box[3]-box[1])-model['depth']['cy'])/model['depth']['fy']*point[0]
        return point, False
    if target['status'] != 'too_far':
        raise ValueError('无有效测量或明确超量程')
    d = model['depth']; x1, y1, x2, y2 = target['depth_box_xyxy']
    forward = target['distance_lower_bound_m']
    return [forward, -((x1+x2)/2-d['cx'])/d['fx']*forward,
            -((y1+y2)/2-d['cy'])/d['fy']*forward], True


class AirSimPerception(Perception):
    def snapshot(self):
        from stage5.airsim.observation_memory import summarize_observations
        value = super().snapshot()
        observations = value.pop('observation_window', [])
        value['target_memory'] = summarize_observations(observations, value.get('generation'), time.monotonic())
        return value

    def worker(self):
        seen_generation = -1; last_target_at = 0.; last_stamp = None
        recent_observations = deque(maxlen=64)
        voxels = None; next_voxels = 0.
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                with self.lock:
                    generation, text = self.generation, self.text
                # 初始规划只取RGB；尚未有stage时不凭缺省红车提示词调用DINO。
                if generation == 0:
                    self.stop.wait(.05); continue
                if generation != seen_generation:
                    self.history.clear(); self.velocity[:] = 0
                    seen_generation = generation; last_stamp = None
                    recent_observations.clear()
                capture_started = time.monotonic()
                rgb, depth = paired_frames(self.config['STAGE5_RGB_URL'], self.config['STAGE5_DEPTH_URL'], 1, .05)
                record_latency(getattr(self, 'output', None), 'frame_fetch', time.monotonic()-capture_started, generation=generation)
                stamp = rgb[0]['sim_time']
                if last_stamp is not None and stamp <= last_stamp:
                    if stamp < last_stamp:
                        raise ValueError('仿真时间回跳')
                    self.stop.wait(.02); continue
                last_stamp = stamp
                png, meta = camera_png('', 1, rgb)
                self.dino_pending = True
                try:
                    self.publish_request_preview(rgb, depth, png, generation)
                    detect_started = time.monotonic()
                    response, _ = self.dino.detect(png, text=text)
                    record_latency(getattr(self, 'output', None), 'dino_request', time.monotonic()-detect_started, generation=generation)
                    processing_started = time.monotonic()
                finally:
                    self.dino_pending = False
                detections, audit = filter_candidates(response['detections'], self.filter_threshold,
                    allowed_words=('car', 'vehicle', 'truck', 'pickup', 'armored', 'van'), role='convoy_vehicle_candidate')
                fused = fuse({**response, 'detections': detections}, rgb[0], depth[0], depth[1], self.model, depth_policy='dominant_layer')
                pose = rgb[0].get('px4_pose')
                if time.monotonic()-last_target_at > 1:
                    self.history.clear(); self.velocity[:] = 0
                chosen = choose_target(fused['targets'])
                tracking = None
                if chosen and pose and time.monotonic()-meta['received'] < 1.:
                    point, proxy = control_point(chosen, self.model)
                    world = camera_point_ned(point, pose, self.model)
                    if proxy:
                        self.history.clear(); self.velocity[:] = 0
                    else:
                        self.history.append((stamp, world))
                    if len(self.history) >= 3 and stamp-self.history[0][0] > .3:
                        ts = np.array([v[0] for v in self.history]); ps = np.array([v[1] for v in self.history])
                        centered = ts-ts.mean(); denominator = centered@centered
                        velocity = (centered[:, None]*(ps-ps.mean(axis=0))).sum(axis=0)/denominator
                        velocity[2] = 0
                        if np.isfinite(velocity).all() and np.linalg.norm(velocity) < 2.5:
                            self.velocity = .5*self.velocity+.5*velocity
                    last_target_at = meta['received']
                    tracking = dict(target=chosen, target_ned=world.tolist(), velocity_ned=self.velocity.tolist(),
                        at=meta['received'], sim_time=stamp, confirmed=True, geometry_available=True, control_proxy=proxy,
                        confirmation_scope='detector candidate with control geometry; identity is for Jev/Qwen to judge',
                        distance_source='range_limit_proxy' if proxy else 'measured_surface',
                        distance_lower_bound_m=chosen.get('distance_lower_bound_m'),
                        roof_reference=('unavailable: range-limit proxy uses bbox center ray' if proxy else
                                        'bbox upper 10% ray at median surface depth; approximate, not roof center'),
                        pose_skew_s=pose['max_skew_s'], clearance_m=self.clearance(depth))
                    tracking['direction_confirmed'] = bool(len(self.history) >= 3 and np.linalg.norm(self.velocity[:2]) > .25)
                if voxels is None or started >= next_voxels:
                    voxels = build(depth[0], depth[1], self.model); next_voxels = time.monotonic()+1
                observation = dict(received=meta['received'], sim_time=stamp, generation=generation,
                                   detections=audit, semantic_targets=fused['targets'], tracking_available=tracking is not None,
                                   capture_pose_available=bool(pose))
                recent_observations.append(observation)  # 空帧也是记忆中的反证，不能省略。
                while recent_observations and time.monotonic()-recent_observations[0]['received'] > 4:
                    recent_observations.popleft()
                output = getattr(self, 'output', None)
                if output:
                    try:
                        with (output/'perception-audit.jsonl').open('a') as stream:
                            stream.write(json.dumps(dict(observation, raw_detections=response['detections']), allow_nan=False)+'\n')
                    except OSError:
                        pass
                preview = dict(image=base64.b64encode(png).decode(), detections=audit,
                               width=response['width'], height=response['height'])
                self.publish_request_preview(rgb, depth, png, generation, preview)
                value = dict(at=meta['received'], sim_time=stamp, generation=generation, tracking=tracking,
                    observation_window=list(recent_observations),
                    detections=detections, detection_candidates=audit, semantic_targets=fused['targets'],
                    detection_received=meta['received'], confirmed=tracking is not None, dino_text=text,
                    semantic_policy='current fresh DINO + RGBD; highest usable score, no cross-frame identity lock',
                    target_selection=dict(policy='highest_score_current_frame', identity_verification='not performed by executor',
                        accepted_candidates=len(detections),
                        scores=[v['score'] for v in detections], motion_estimate_assumes_same_target=True),
                    local_space=dict(motion_candidates=copy.deepcopy(voxels['motion_candidates']), front_clearance_m=self.clearance(depth)))
                record_latency(getattr(self, 'output', None), 'perception_processing', time.monotonic()-processing_started, generation=generation)
                record_latency(getattr(self, 'output', None), 'capture_to_perception', time.monotonic()-meta['received'], generation=generation)
                with self.lock:
                    if generation == self.generation:
                        self.latest = value; self.error = None
                        if tracking:
                            self.last_seen = time.monotonic()
                        self.frame = dict(png=png, sim_time=stamp, received=meta['received'], generation=generation)
            except Exception as exc:
                with self.lock:
                    self.error = type(exc).__name__
                    self.latest = {}  # 不让上一帧成功掩盖本帧错误。
            self.stop.wait(max(.02, .1-(time.monotonic()-started)))

    def clearance(self, depth):
        meta, raw = depth; d = self.model['depth']
        image = np.ndarray((meta['height'], meta['width']), dtype='<f4', buffer=raw, strides=(meta['step'], 4))[::4, ::4]
        yy, xx = np.mgrid[0:meta['height']:4, 0:meta['width']:4]
        left = -(xx+.5-d['cx'])/d['fx']*image
        up = -(yy+.5-d['cy'])/d['fy']*image
        body = self.model['body_center_camera_flu_m']
        valid = np.isfinite(image) & (image > self.model['near_m']) & (image < self.model['far_m'])
        inside = valid & (np.abs(left-body[1]) < .75) & (np.abs(up-body[2]) < .75)
        return max(0., float(image[inside].min())-body[0]) if inside.any() else self.model['far_m']
