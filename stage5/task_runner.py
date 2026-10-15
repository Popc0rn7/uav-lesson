"""可注入模型/执行器的任务生命周期；只负责账本、路由与版本，不替Qwen验收。"""
import copy
import json
from pathlib import Path
import queue
import threading
import time

from agent_contracts import allocation, plan, progress_key, review, positive
from planning_hints import guidance
from agent_errors import FatalControl
from evidence import write_json


class TaskEnd(RuntimeError):
    pass


class TaskRunner:
    def __init__(self, task, model, runtime_factory, output, budget=10, timeout=300,
                 default_seconds=60, initial_plan=None, plan_only=False, clock=time.monotonic,
                 request_timeout=120, summary_timeout=30, simulation=None):
        self.simulation = simulation
        self.task, self.model, self.runtime_factory = task, model, runtime_factory
        positive(budget, 'task budget', True)
        for name, value in (('task timeout',timeout),('request timeout',request_timeout),
                            ('summary timeout',summary_timeout),('default seconds',default_seconds)):
            positive(value,name)
        self.output = Path(output); self.output.mkdir(parents=True, exist_ok=True)
        self.clock = clock; self.started = clock(); self.deadline = self.started + timeout
        self.limit, self.request_timeout, self.summary_timeout = budget, request_timeout, min(30,summary_timeout)
        self.calls = self.summary_calls = 0
        self.default_seconds, self.initial_plan, self.plan_only = default_seconds, initial_plan, plan_only
        self.runtime = None; self.current_plan = None; self.index = 0; self.revision = 1
        self.reports = []; self.accepted = []; self.progress = {}; self.total_jev = 0
        self.model_costs = []
        self.finalized = False; self.in_summary = False
        self.execution_ended = None
        self.ui_runtime = {}
        self.ui_updated = 0; self.qwen_activity = None; self.last_decision = None

    def write(self, name, value):
        write_json(self.output / name, value)

    def event(self, kind, **data):
        if 'elapsed_s' in data:
            data['stage_elapsed_s'] = data.pop('elapsed_s')
        value = {**data, 'elapsed_s': self.clock() - self.started, 'event': kind}
        with (self.output / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')

    def ledger(self):
        now = self.clock()
        return {'qwen_budget': self.limit, 'qwen_execution_calls': self.calls,
                'qwen_summary_calls': self.summary_calls, 'qwen_total_calls': self.calls + self.summary_calls,
                'jev_calls': self.total_jev, 'elapsed_s': now - self.started,
                'execution_elapsed_s': (self.execution_ended if self.execution_ended is not None else now)-self.started,
                'finalization_elapsed_s': now-self.execution_ended if self.execution_ended is not None else 0,
                'remaining_timeout_s': max(0, self.deadline - now)}

    def check(self):
        if self.clock() >= self.deadline:
            raise TaskEnd('timeout')

    def publish_ui(self, force=False):
        now = self.clock()
        if not force and now-self.ui_updated < .5:
            return
        self.ui_updated = now
        try:
            try:
                runtime = self.runtime.ui_snapshot() if hasattr(self.runtime, 'ui_snapshot') else {}
                self.ui_runtime = runtime
            except Exception:
                runtime = self.ui_runtime
            if self.finalized:
                runtime = {**runtime, 'active': False, 'jev_pending': False, 'dino_pending': False}
            value = dict(updated_monotonic=now, task=self.task, plan=self.current_plan,
                         current_index=self.index, revision=self.revision, accepted=self.accepted,
                         qwen_activity=self.qwen_activity, last_decision=self.last_decision,
                         ledger=self.ledger(), finalized=self.finalized, runtime=runtime,
                         qwen_metrics=getattr(self.model,'last_metrics',{}),
                         simulation_paused=bool(self.simulation and self.simulation.paused))
            self.write('ui.json', value)
        except (OSError, ValueError):
            pass  # 监控写入失败不改变飞行生命周期。

    def service(self):
        if not self.in_summary:
            self.check()
        if self.runtime:
            self.runtime.service()
        self.publish_ui()

    def context(self):
        try:
            observation = self.runtime.snapshot() if self.runtime else {}
        except Exception as exc:
            observation = {'snapshot_error': type(exc).__name__}
        stages = self.current_plan['stages'] if self.current_plan else []
        current = stages[self.index] if self.index < len(stages) else None
        latest_progress = self.progress.get(progress_key(current), {}) if current else {}
        return {'task': self.task, 'default_duration_s': self.default_seconds,
                'execution_guidance': guidance(observation, current, self.default_seconds, latest_progress),
                'qwen_completed_request_costs': list(self.model_costs),
                'plan': self.current_plan, 'current_index': self.index, 'plan_revision': self.revision,
                'accepted': self.accepted, 'stage_reports': self.reports, 'usage': self.ledger(),
                'observation': observation}

    def images(self):
        try:
            return self.runtime.images() if self.runtime else []
        except Exception as exc:
            self.event('image_unavailable', error_type=type(exc).__name__)
            return []

    def invoke(self, purpose, payload, images, summary=False):
        if summary:
            if self.summary_calls:
                raise RuntimeError('最终总结只能请求一次')
            self.summary_calls = 1
            until = self.clock() + self.summary_timeout
        else:
            self.check()
            if self.calls >= self.limit:
                raise TaskEnd('budget_exhausted')
            self.calls += 1
            until = min(self.deadline, self.clock() + self.request_timeout)
        self.qwen_activity = purpose
        self.publish_ui(force=True)
        self.event('qwen_request', purpose=purpose, execution_call=self.calls, summary_call=self.summary_calls)
        self.write('ledger.json', self.ledger())
        number = self.calls if not summary else 'summary'
        image_records = []
        for index, frame in enumerate(images):
            path = self.output / f'qwen-{number}-frame-{index}.png'
            path.write_bytes(frame['png'])
            image_records.append({'path': str(path), **{k: v for k, v in frame.items() if k != 'png'}})
        self.write(f'qwen-{number}-input.json', {'purpose': purpose, 'payload': payload, 'images': image_records})
        answer = queue.Queue(maxsize=1)
        request_started = self.clock()
        def request():
            try:
                answer.put((True, self.model.request(purpose, payload, images, max(.01, until - self.clock()))))
            except (Exception, KeyboardInterrupt) as exc:
                answer.put((False, exc))
        if self.simulation:
            self.simulation.begin(self.runtime, self.event)
        try:
            threading.Thread(target=request, daemon=True).start()
            while True:
                if self.clock() >= until:
                    if not summary:
                        self.check()
                    raise TimeoutError('Qwen request timeout; late result discarded')
                if self.simulation:
                    self.simulation.tick()
                self.service()
                try:
                    ok, value = answer.get(timeout=.02)
                except queue.Empty:
                    continue
                if self.clock() >= until:
                    if not summary:
                        self.check()
                    raise TimeoutError('late Qwen response discarded')
                self.model_costs.append({'purpose': purpose, 'elapsed_s': self.clock()-request_started,
                                         'success': ok})
                if not ok:
                    raise value
                if getattr(self.model, 'last_metrics', None):
                    self.write(f'qwen-{number}-metrics.json', self.model.last_metrics)
                    self.event('qwen_usage', purpose=purpose, **{k:v for k,v in self.model.last_metrics.items() if k!='purpose'})
                if getattr(self.model, 'last_request', None):
                    self.write(f'qwen-{number}-request.json', self.model.last_request)
                self.qwen_activity = None
                self.last_decision = value
                self.write(f'qwen-{number}-output.json', value)
                return value
        finally:
            if self.simulation:
                self.simulation.finish()

    def ask(self, purpose, validator):
        repair = None; network_errors = 0
        while True:
            self.check()
            payload = self.context()
            if repair: payload['previous_error'] = repair
            try:
                value = self.invoke(purpose, payload, self.images())
                result = validator(value)
                self.event('qwen_result', purpose=purpose, result=result)
                return result
            except (TaskEnd, FatalControl, KeyboardInterrupt):
                raise
            except Exception as exc:
                self.qwen_activity = None
                # 仅本地协议校验信息可回传；网络异常正文可能含凭据，不记录。
                if isinstance(exc, ValueError):
                    if str(exc).startswith('unsupported_task:'):
                        raise TaskEnd('unsupported_task') from None
                    repair = str(exc)[:500]
                    self.event('invalid_qwen_result', reason=repair)
                    continue
                network_errors += 1
                status = getattr(exc, 'status', None)
                self.event('qwen_error', error_type=type(exc).__name__, http_status=status)
                if status is not None and status not in (408, 429) and status < 500:
                    raise TaskEnd('qwen_unavailable') from None
                if network_errors >= 3:
                    raise TaskEnd('qwen_unavailable') from None
                until = self.clock() + min(2 ** (network_errors - 1), 4)
                while self.clock() < until:
                    self.service(); time.sleep(.02)
                repair = '上次请求未成功，请根据当前事实继续。'

    def save_plan(self):
        self.write(f'plan-{self.revision:03d}.json', self.current_plan)
        self.write('plan.json', self.current_plan)

    def run(self):
        outcome = 'failed'; reason = None; summary = None
        self.write('task.json', {'task': self.task, 'qwen_budget': self.limit,
            'qwen_model': getattr(self.model,'model_id',None),
            'timeout_s': self.deadline-self.started, 'started_monotonic': self.started,
            'deadline_monotonic': self.deadline, 'initial_plan_source': 'provided_plan' if self.initial_plan else 'qwen'})
        try:
            self.runtime = self.runtime_factory(self.deadline)
            self.service()
            self.current_plan = plan(self.initial_plan, self.task) if self.initial_plan else self.ask('plan', lambda value: plan(value, self.task))
            self.save_plan()
            if self.plan_only:
                outcome = 'planned'
            else:
                while self.index < len(self.current_plan['stages']):
                    self.check()
                    if self.calls >= self.limit:
                        raise TaskEnd('budget_exhausted')  # 至少预留一次阶段验收。
                    current = self.current_plan['stages'][self.index]
                    key = progress_key(current)
                    progress = self.progress.setdefault(key, {'valid_follow_s': 0., 'observed_s': 0.})
                    attempt = len(self.reports) + 1
                    directory = self.output / f'attempt-{attempt:03d}'; directory.mkdir()
                    tag = {'plan_revision': self.revision, 'stage_id': current['id'], 'attempt': attempt}
                    self.event('stage_start', **tag, allocation=current['allocation'])
                    report = None
                    try:
                        self.runtime.start(current, progress, tag, directory)
                        while report is None:
                            self.service()
                            report = self.runtime.step()
                            if report is None: time.sleep(.02)
                    except (TaskEnd, FatalControl, KeyboardInterrupt):
                        raise
                    except Exception as exc:
                        report = {'status': 'failed', 'reason': 'executor_error', 'error_type': type(exc).__name__}
                    finally:
                        report = self.runtime.end(report or {'status': 'failed', 'reason': 'task_stopped'})
                        report.update(tag)
                        self.reports.append(report)
                        self.total_jev += report['jev_calls']
                        self.write(f'attempt-{attempt:03d}/report.json', report)
                        self.write('ledger.json', self.ledger())
                        self.event('stage_end', **report)
                    decision = self.ask('review', lambda value: review(value, self.current_plan, self.index, self.task))
                    self.write(f'attempt-{attempt:03d}/review.json', decision)
                    action = decision['action']
                    if action == 'abort':
                        self.event('task_aborted', assessment=decision['assessment'])
                        raise TaskEnd('qwen_aborted')
                    if action == 'accept':
                        self.accepted.append({'stage': copy.deepcopy(current), 'report': copy.deepcopy(report),
                                              'review': decision})
                        self.index += 1
                    elif action == 'redo':
                        current['allocation'] = allocation(decision['allocation'])
                        self.revision += 1; self.save_plan()
                    else:
                        if action == 'modify_stage': self.current_plan['stages'][self.index] = decision['stage']
                        else: self.current_plan['stages'][self.index:] = decision['stages']
                        self.revision += 1; self.save_plan()
                outcome = 'completed'
        except TaskEnd as exc:
            reason = str(exc)
        except FatalControl as exc:
            reason = 'control_fault: ' + str(exc)
        except KeyboardInterrupt:
            reason = 'interrupted'
        except Exception as exc:
            reason = 'runtime_error: ' + type(exc).__name__
            self.event('runtime_error', error_type=type(exc).__name__)
        finally:
            if self.simulation:
                try: self.simulation.finish()
                except FatalControl as exc:
                    outcome = 'failed'; reason = str(exc)
                    self.event('simulation_restore_error', reason=reason)
            self.execution_ended = self.clock()
            self.in_summary = True
            if self.runtime:
                try: self.runtime.freeze()
                except Exception as exc: self.event('stop_error', error_type=type(exc).__name__)
            terminal = {'outcome': outcome, 'reason': reason, 'context': self.context()}
            self.write('terminal.json', terminal)
            try:
                summary = self.invoke('summary', terminal, self.images(), summary=True)
                if not isinstance(summary.get('summary'), str) or not summary['summary'].strip():
                    raise ValueError('总结缺少 summary 文本')
                summary['source'] = 'qwen'
            except (Exception, KeyboardInterrupt) as exc:
                if isinstance(exc, FatalControl):
                    outcome = 'failed'; reason = 'control_fault: '+str(exc)
                summary = {'summary': f"任务{outcome}；结束原因={reason}；接受{len(self.accepted)}个阶段；"
                           f"Qwen执行调用{self.calls}次，Jev调用{self.total_jev}次。",
                           'source': 'local_fallback', 'error_type': type(exc).__name__}
            if self.simulation:
                try: self.simulation.finish()
                except FatalControl as exc:
                    outcome = 'failed'; reason = 'control_fault: '+str(exc)
                    self.event('simulation_restore_error', reason=reason)
            terminal.update(outcome=outcome, reason=reason)
            self.write('terminal.json', terminal)
            self.write('summary.json', summary)
            self.finalized = True
            self.qwen_activity = None
            self.publish_ui(force=True)
            if self.runtime:
                try: self.runtime.close()
                except Exception as exc: self.event('close_error', error_type=type(exc).__name__)
            self.write('ledger.json', self.ledger())
            self.publish_ui(force=True)
        print(f"TASK {outcome}: {reason or 'accepted'}\n{summary['summary']}\nTask evidence: {self.output}", flush=True)
        return 0 if outcome in ('completed', 'planned') else 130 if reason == 'interrupted' else 1
