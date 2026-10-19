"""改编自 jev-drone/tactics.py：异步 Jev 战术判断，许可证见 LICENSE.jev-drone。

保留单 worker、单槽队列、限频、预算、指纹缓存；输出建议，不控制 PX4。
"""
import hashlib
import json
import math
import queue
import re
import threading
import time

MANEUVERS = {
    'hold_course': '继续朝目标跟随。仅在目标方向可信、前进路径 clear 且需要接近时选择。',
    'gap_left': '向左前方绕行或换视角观察，仅在相应候选路径 clear 时选择。',
    'gap_right': '向右前方绕行或换视角观察，仅在相应候选路径 clear 时选择。',
    'climb': '向上改变观察位置，仅在 up_1m 候选路径 clear 时选择。',
    'brake': '保持位置或减速等待。目标太近、路径 blocked/unknown、信息陈旧时优先。',
    'reacquire': '需要重新确认目标或其方向。表示观察意图，不授权盲目移动。',
}
DEFAULT = dict(maneuver='brake', risk=None, confidence=0, target_ambiguous=None,
               source='default', probabilities={}, actionable=False)
PATHS = {'hold_course': 'forward_1m', 'gap_left': 'forward_left_1m',
         'gap_right': 'forward_right_1m', 'climb': 'up_1m'}


def questions():
    from decision_client import Choice, Noul, Score
    return {
        'maneuver': Choice(instructions='依据用户任务、目标候选和局部空间，选择下一项战术行为。'
            'unknown 不是 clear；too_far 是超过量程的信息，不是目标丢失。'
            '深度是可见表面而非车中心；没有目标运动方向时不能声称已到车后方。', criteria=MANEUVERS),
        'risk': Score(instructions='当前追踪或拟移动的风险有多大？',
                      criteria=['clear and open', 'uncertain or tight', 'immediate collision risk']),
        'target_ambiguous': Noul(instructions='目标身份、方向或距离是否仍有会影响本轮动作选择的歧义？'
            '多候选、混合深度和疑似遮挡都需要考虑；单纯 too_far 不意味着目标消失。',
            criteria={'true': '需要继续观察确认', 'false': '已有足够信息选择本轮行为'}),
    }


def build_state(targets, voxels, capture, mission):
    return dict(mission=mission,
        aircraft=dict(type='PX4 x500_experiment quadrotor', observation_frame='camera_flu',
                      axes='x forward, y left, z up', units='m',
                      camera_to_body_center_m=voxels['body_center_camera_m'],
                      radius_m=voxels['drone_radius_m'], target_motion_direction='not estimated'),
        observed=dict(target_candidates=targets['targets'],
                      target_response_source=targets['response_source'],
                      rgb_sim_time=targets['rgb_sim_time'], depth_sim_time=targets['depth_sim_time'],
                      frame_skew_s=targets['frame_skew_s'],
                      observation_age_at_submission_s=time.monotonic()-capture['received'],
                      local_space={k:v for k,v in voxels.items() if k not in
                          ('occupied_points_m', 'observation_age_s', 'fresh')},
                      note='未提供真实目标姿态、世界位置、精确分割或目标历史；不要猜测。'),
        behavior_options=MANEUVERS, execution_mode='advisory_only')


class Tactician:
    def __init__(self, config, client=None, question_set=None):
        self.hz = float(config.get('JEV_CALL_HZ', '1'))
        self.budget = int(config.get('JEV_CALL_BUDGET', '10'))
        self.timeout = float(config.get('JEV_TIMEOUT', '10'))
        self.ttl = float(config.get('JEV_STALE_AFTER_S', '1.5'))
        self.model = config.get('JEV_MODEL') or ('jev-decision' if config.get('JEV_BACKEND') == 'vllm' else 'jev-latest')
        self.retry_base = float(config.get('JEV_RETRY_BASE_S', '1'))
        self.max_failures = int(config.get('JEV_MAX_CONSECUTIVE_ERRORS', '3'))
        self._secrets = [v for k,v in config.items() if v and any(s in k.upper() for s in ('KEY','TOKEN','SECRET','PASSWORD','PROXY'))]
        if not math.isfinite(self.retry_base) or self.retry_base <= 0 or self.max_failures < 1:
            raise ValueError('Jev 重试间隔与连续失败上限必须为正数')
        if not all(math.isfinite(v) and v > 0 for v in (self.hz, self.timeout, self.ttl)) or self.budget < 1:
            raise ValueError('Jev 频率、预算、超时和 TTL 必须为正数')
        if client is None:
            from decision_client import DecisionClient
            self.client = DecisionClient(config, self.timeout)
            self.questions = question_set or questions()
        else:
            self.client, self.questions = client, {}
        self.attempts = self.calls = self.errors = 0
        self._queue = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._latest = dict(DEFAULT)
        self._pending = False
        self._last_sent = float('-inf')
        self._last_key = None
        self._observed_at = None
        self._failures = 0
        self._retry_at = 0
        self._terminal_error = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    @staticmethod
    def fingerprint(state):
        compact = dict(mission=state['mission'], targets=state['observed']['target_candidates'],
                       stage=state.get('stage'),
                       progress=state.get('progress'),
                       tracking=state['observed'].get('tracking'),
                       recovery=state.get('execution_health'),
                       source=state['observed']['target_response_source'],
                       actions=state['observed']['local_space']['motion_candidates'])
        # 忽略时间戳，但保留目标和任务，防止缓存跨目标/指令复用。
        return hashlib.sha256(json.dumps(compact, sort_keys=True).encode()).hexdigest()

    def offer(self, state, observed_at):
        now = time.monotonic()
        key = self.fingerprint(state)
        with self._lock:
            if self._terminal_error or now < self._retry_at:
                return False
            if self._pending or self.attempts >= self.budget or now-self._last_sent < 1/self.hz:
                return False
            # 缓存不能靠新一帧重复 offer 刷新原决策的观测时间。
            if key == self._last_key and self._observed_at is not None and now-self._observed_at <= self.ttl:
                return False
            self._pending = True
            self._last_sent, self._last_key = now, key
            self._queue.put_nowait((state, observed_at))
        return True

    def read(self):
        with self._lock:
            result = dict(self._latest)
            age = time.monotonic()-self._observed_at if self._observed_at is not None else None
        result.update(observation_age_s=age, stale=age is None or age > self.ttl)
        result['actionable'] = result['source'] == 'jev' and not result['stale'] and result.get('path_allowed', False)
        return result

    def wait_result(self):
        deadline = time.monotonic()+self.timeout+2
        while time.monotonic() < deadline:
            with self._lock:
                if not self._pending:
                    return self.read_unlocked()
            time.sleep(.02)
        return dict(DEFAULT, source='timeout', stale=True)

    def read_unlocked(self):
        result = dict(self._latest)
        age = time.monotonic()-self._observed_at if self._observed_at is not None else None
        result.update(observation_age_s=age, stale=age is None or age > self.ttl)
        result['actionable'] = result['source'] == 'jev' and not result['stale'] and result.get('path_allowed', False)
        return result

    @property
    def pending(self):
        with self._lock:
            return self._pending

    def _worker(self):
        try:
            self._process_queue()
        finally:
            self.client.close()

    def _process_queue(self):
        while not self._stop.is_set():
            try:
                state, observed_at = self._queue.get(timeout=.2)
            except queue.Empty:
                continue
            with self._lock:
                if self._stop.is_set():
                    self._pending = False
                    self._queue.task_done()
                    continue
                self.attempts += 1
            try:
                started = time.monotonic()
                response = self.client.system_one(state=state, model=self.model, questions=self.questions)
                answers = response.answers
                maneuver = answers['maneuver'].choice
                confidence, risk = float(answers['maneuver'].confidence), float(answers['risk'].score)
                ambiguous = float(answers['target_ambiguous'].noul) if 'target_ambiguous' in answers else None
                if maneuver not in MANEUVERS or not 0 <= confidence <= 1 or not 0 <= risk <= 2 or ambiguous is not None and not 0 <= ambiguous <= 1:
                    raise ValueError('Jev 返回选项或分数不合法')
                path = PATHS.get(maneuver)
                candidate = state['observed']['local_space']['motion_candidates'].get(path, {}) if path else {}
                allowed = path is None or candidate.get('status') == 'clear'
                if (state.get('execution_mode') == 'simulation_follow' and maneuver == 'hold_course'
                        and candidate.get('execution_policy') == 'cautious' and candidate.get('status') == 'unknown'):
                    allowed = True
                judgment = dict(maneuver=maneuver, confidence=confidence, risk=risk,
                    target_ambiguous=ambiguous, probabilities=answers['maneuver'].probabilities,
                    source='jev', latency_s=time.monotonic()-started,
                    tokens=(response.usage.input_tokens or 0)+(response.usage.output_tokens or 0),
                    path_allowed=allowed, effective_maneuver=maneuver if allowed else 'brake',
                    guard_reason=None if allowed else 'candidate path blocked or unknown',
                    execution_mode='advisory_only')
                if 'stage_status' in self.questions:
                    status=answers['stage_status'].choice
                    if status not in self.questions['stage_status'].criteria:
                        raise ValueError('Jev stage_status 不合法')
                    judgment['stage_status']=status
                    if status!='running':
                        judgment.update(path_allowed=False,effective_maneuver='brake',guard_reason='stage '+status)
                if 'stage_reason' in self.questions:
                    reason = answers['stage_reason'].choice
                    if reason not in self.questions['stage_reason'].criteria:
                        raise ValueError('Jev stage_reason 不合法')
                    judgment['stage_reason'] = reason
                for field in ('plan_revision','stage_id','attempt'):
                    if field in state:
                        judgment[field] = state[field]
                with self._lock:
                    self.calls += 1
                    self._failures = 0
                    self._retry_at = 0
                    self._latest, self._observed_at = judgment, observed_at
            except Exception as exc:
                with self._lock:
                    self.errors += 1
                    self._failures += 1
                    # 仅提取脱敏的服务端说明，不记录整个异常、请求或响应头。
                    self._latest = dict(DEFAULT, source='error', error_type=type(exc).__name__)
                    status=getattr(exc,'status',None)
                    self._latest['error_http_status']=status if isinstance(status,int) else None
                    self._latest['error_category']=('access_policy' if status==451 else 'authentication' if status in (401,403) else
                        'quota' if status==402 else 'rate_limit' if status==429 else
                        'server' if isinstance(status,int) and status>=500 else 'request_or_network')
                    retryable = status is None or status in (408,429) or isinstance(status,int) and status>=500
                    self._terminal_error = not retryable or self._failures >= self.max_failures
                    delay = min(8., self.retry_base*2**min(self._failures-1,8))
                    retry_ms = getattr(exc,'retry_after_ms',None)
                    if isinstance(retry_ms,(int,float)) and math.isfinite(retry_ms):
                        delay=max(delay,max(0,retry_ms/1000))
                    self._retry_at = time.monotonic()+delay
                    self._latest.update(retryable=retryable,terminal_error=self._terminal_error,
                        consecutive_errors=self._failures,retry_after_s=delay)
                    body=getattr(exc,'body',None)
                    if isinstance(body,dict):
                        message=next((body[k] for k in ('title','message','detail','error') if isinstance(body.get(k),str)),None)
                        if message:
                            for secret in self._secrets:message=message.replace(secret,'[REDACTED]')
                            message=re.sub(r'https?://\S+|\b(?:Bearer\s+\S+|sk-[\w-]+)','[REDACTED]',message)
                            self._latest['error_message']=' '.join(message.split())[:300]
                    self._observed_at = observed_at
                    self._last_key = None
            finally:
                with self._lock:
                    self._pending = False
                self._queue.task_done()

    def close(self, wait=True):
        self._stop.set()
        if wait:
            self._thread.join(timeout=self.timeout+1)

    def stats(self):
        with self._lock:
            return dict(calls=self.calls, attempts=self.attempts, errors=self.errors,
                        call_budget=self.budget, model=self.model,
                        backend=getattr(self.client, 'backend', 'injected'))
