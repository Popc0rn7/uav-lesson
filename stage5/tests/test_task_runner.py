import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_contracts import plan, review, progress_key
from task_runner import TaskRunner, FatalControl


def stage(id='follow', **updates):
    value=dict(id=id,goal='跟随红车',skill='follow_red_vehicle',dino_text='a red car. a red box.',
        horizontal_distance_m=8,above_m=2,duration_s=5,completion_criteria='跟随5秒',failure_criteria='持续丢失',
        allowed_skills=['hold_course','brake','reacquire'],allocation={'budget':2,'timeout':10})
    value.update(updates); return value


def make_plan(*stages):
    return dict(version=2,mission='跟随红车',stages=list(stages or [stage()]))


class Model:
    def __init__(self, responses): self.responses=list(responses); self.calls=[]
    def request(self,purpose,payload,images,timeout):
        self.calls.append((purpose,copy.deepcopy(payload)))
        if purpose=='summary': return {'summary':'测试总结'}
        result=self.responses.pop(0)
        if isinstance(result,BaseException): raise result
        return copy.deepcopy(result)


class Runtime:
    def __init__(self,statuses=None):
        self.statuses=list(statuses or ['done']);self.starts=[];self.frozen=False;self.closed=False
    def service(self): pass
    def snapshot(self): return {'confirmed':True}
    def images(self): return []
    def start(self,current,progress,tag,directory):
        self.progress=progress;self.current=current
        self.starts.append({'stage':copy.deepcopy(current),'progress':dict(progress),'tag':dict(tag)})
    def step(self):
        self.progress['valid_follow_s']+=2
        status=self.statuses.pop(0)
        return {'status':status,'reason':status}
    def end(self,result): return {**result,'jev_calls':2,'progress':dict(self.progress)}
    def freeze(self): self.frozen=True
    def close(self): self.closed=True


class TaskTests(unittest.TestCase):
    def test_summary_resume_failure_cannot_leave_completed_outcome(self):
        from unittest.mock import Mock
        simulation=Mock();simulation.paused=False
        simulation.finish.side_effect=[None,None,None,FatalControl('resume failed'),None]
        runner,model,runtime,root,result=self.execute([make_plan(),{'action':'accept'}],simulation=simulation)
        self.assertEqual(result,1)
        self.assertEqual(json.loads((root/'terminal.json').read_text())['outcome'],'failed')
        self.assertIn('resume failed',json.loads((root/'terminal.json').read_text())['reason'])


    def test_review_cannot_replace_explicit_follow_duration(self):
        with self.assertRaisesRegex(ValueError,'用户明确指定'):
            review({'action':'modify_stage','stage':stage(duration_s=60,
                completion_criteria='达到60秒')},make_plan(),0,task='跟随10秒')


    def test_plan_cannot_replace_explicit_task_duration_with_default(self):
        with self.assertRaisesRegex(ValueError,'用户明确指定'):
            plan(make_plan(stage(duration_s=60,goal='跟随红车',completion_criteria='累计有效时长达到60秒')),
                 task='观察红车，然后跟随10秒')


    def test_mismatched_duration_is_rejected_before_execution(self):
        bad=make_plan(stage(duration_s=60,goal='跟随红车10秒',completion_criteria='有效跟随达到10秒'))
        runner,model,runtime,root,result=self.execute([bad,make_plan(),{'action':'accept'}],budget=4)
        self.assertEqual(result,0)
        self.assertEqual(len(runtime.starts),1)
        self.assertEqual(runtime.starts[0]['stage']['duration_s'],5)
        self.assertIn('duration_s',model.calls[1][1]['previous_error'])

    def test_model_exception_restores_simulation_wait(self):
        from unittest.mock import Mock
        simulation=Mock();simulation.paused=False
        runner,model,runtime,root,result=self.execute([RuntimeError('network')]*3,simulation=simulation)
        self.assertEqual(result,1)
        self.assertEqual(simulation.begin.call_count,4)  # 三次执行请求＋最终总结
        self.assertGreaterEqual(simulation.finish.call_count,simulation.begin.call_count)


    def test_abort_ends_task_without_redo_or_accept(self):
        runner, model, runtime, root, result = self.execute([
            make_plan(), {'action':'abort', 'assessment':'目标丢失且无搜索能力'}], ['failed'])
        self.assertEqual(result, 1)
        terminal = json.loads((root/'terminal.json').read_text())
        self.assertEqual(terminal['reason'], 'qwen_aborted')
        self.assertEqual(len(runtime.starts), 1)
        self.assertFalse(runner.accepted)
        ui = json.loads((root/'ui.json').read_text())
        self.assertTrue(ui['finalized'])
        self.assertIsNone(ui['qwen_activity'])
        self.assertEqual(runner.summary_calls, 1)

    def test_terminal_ui_survives_closed_runtime_snapshot_failure(self):
        class ClosedRuntime(Runtime):
            def ui_snapshot(self):
                if self.closed:
                    raise RuntimeError('closed')
                return {'active':True}
        with tempfile.TemporaryDirectory() as directory:
            runtime = ClosedRuntime()
            runner = TaskRunner('任务', Model([make_plan(), {'action':'accept'}]),
                                lambda deadline:runtime, directory, timeout=10)
            self.assertEqual(runner.run(), 0)
            ui = json.loads((Path(directory)/'ui.json').read_text())
            self.assertTrue(ui['finalized'])
            self.assertFalse(ui['runtime']['active'])


    def test_planner_and_reviewer_receive_costs_and_current_progress(self):
        runner,model,runtime,root,result=self.execute(
            [make_plan(),{'action':'accept'}],budget=2)
        self.assertEqual(result,0)
        planning=model.calls[0][1]
        reviewing=model.calls[1][1]
        self.assertIn('execution_guidance',planning)
        self.assertEqual(reviewing['execution_guidance']['remaining_qualified_follow_s'],3)
        self.assertEqual(reviewing['qwen_completed_request_costs'][0]['purpose'],'plan')
        self.assertGreaterEqual(reviewing['qwen_completed_request_costs'][0]['elapsed_s'],0)

    def execute(self,responses,statuses=None,budget=10,**kwargs):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);model=Model(responses);runtime=Runtime(statuses)
        runner=TaskRunner('跟随红车',model,lambda deadline:runtime,root,budget=budget,timeout=10,**kwargs)
        result=runner.run()
        return runner,model,runtime,root,result

    def test_failed_stage_can_be_accepted_and_summary_is_extra(self):
        runner,model,runtime,root,result=self.execute([make_plan(),{'action':'accept'}],['budget_exhausted'],budget=2)
        self.assertEqual(result,0)
        self.assertEqual([p for p,c in model.calls],['plan','review','summary'])
        self.assertEqual(runner.calls,2);self.assertEqual(runner.summary_calls,1)
        self.assertEqual(runner.accepted[0]['report']['status'],'budget_exhausted')
        self.assertTrue(runtime.frozen and runtime.closed)

    def test_redo_inherits_progress_and_records_all_consumption(self):
        responses=[make_plan(),{'action':'redo','allocation':{'budget':3,'timeout':10}},{'action':'accept'}]
        runner,model,runtime,root,result=self.execute(responses,['failed','done'])
        self.assertEqual(result,0)
        self.assertEqual(runtime.starts[1]['progress']['valid_follow_s'],2)
        self.assertEqual(runner.reports[1]['progress']['valid_follow_s'],4)
        self.assertEqual(runner.total_jev,4)
        self.assertEqual(runner.calls,3)
        self.assertEqual(runtime.starts[1]['stage']['allocation']['budget'],3)
        self.assertTrue((root/'plan-002.json').exists())

    def test_modify_stage_revalidates_new_goal_but_keeps_history(self):
        runner,model,runtime,root,result=self.execute([make_plan(),
            {'action':'modify_stage','stage':stage(horizontal_distance_m=10)}, {'action':'accept'}],['failed','done'])
        self.assertEqual(result,0)
        self.assertEqual(runtime.starts[1]['progress']['valid_follow_s'],0)
        self.assertEqual(runner.reports[0]['progress']['valid_follow_s'],2)
        self.assertEqual(runner.total_jev,4)

    def test_modify_plan_replaces_suffix_only(self):
        original=make_plan(stage('accepted'),stage('current'),stage('removed'))
        runner,model,runtime,root,result=self.execute([original,{'action':'accept'},
            {'action':'modify_plan','stages':[stage('new')]},{'action':'accept'}],['done','failed','done'])
        self.assertEqual(result,0)
        self.assertEqual([s['id'] for s in runner.current_plan['stages']],['accepted','new'])
        self.assertEqual(runner.accepted[0]['stage']['id'],'accepted')
        self.assertEqual(runtime.starts[1]['progress']['valid_follow_s'],0)

    def test_no_stage_started_without_review_budget(self):
        runner,model,runtime,root,result=self.execute([make_plan()],budget=1)
        self.assertEqual(result,1);self.assertFalse(runtime.starts)
        self.assertEqual(runner.summary_calls,1)
        self.assertEqual(json.loads((root/'terminal.json').read_text())['reason'],'budget_exhausted')

    def test_invalid_plan_repair_counts_request(self):
        runner,model,runtime,root,result=self.execute([{},make_plan(),{'action':'accept'}],budget=3)
        self.assertEqual(result,0);self.assertEqual(runner.calls,3)
        self.assertIn('previous_error',model.calls[1][1])

    def test_budget_exhaustion_after_redo_does_not_restart(self):
        runner,model,runtime,root,result=self.execute([make_plan(),
            {'action':'redo','allocation':{'budget':20,'timeout':30}}],budget=2)
        self.assertEqual(result,1);self.assertEqual(len(runtime.starts),1)
        self.assertEqual(runner.summary_calls,1)

    def test_timeout_discards_late_planning_and_still_summarizes(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        class Slow(Model):
            def request(self,purpose,payload,images,timeout):
                self.calls.append((purpose,{}))
                if purpose=='summary':return {'summary':'超时总结'}
                time.sleep(.15);return make_plan()
        model=Slow([]);runtime=Runtime()
        runner=TaskRunner('任务',model,lambda deadline:runtime,directory.name,timeout=.03)
        self.assertEqual(runner.run(),1)
        time.sleep(.16)
        self.assertFalse(runtime.starts)
        self.assertEqual(runner.summary_calls,1)
        self.assertEqual(json.loads((Path(directory.name)/'terminal.json').read_text())['reason'],'timeout')

    def test_summary_failure_is_not_retried(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        class BrokenSummary(Model):
            def request(self,purpose,payload,images,timeout):
                if purpose=='summary':raise RuntimeError('private network text')
                return super().request(purpose,payload,images,timeout)
        model=BrokenSummary([make_plan(),{'action':'accept'}]);runtime=Runtime()
        runner=TaskRunner('任务',model,lambda deadline:runtime,directory.name,timeout=10)
        self.assertEqual(runner.run(),0)
        self.assertEqual(runner.summary_calls,1)
        self.assertEqual(json.loads((Path(directory.name)/'summary.json').read_text())['source'],'local_fallback')

    def test_hard_control_fault_does_not_route_to_redo(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        runtime=Runtime()
        runtime.service=lambda: (_ for _ in ()).throw(FatalControl('lost')) if not runtime.frozen else None
        model=Model([])
        runner=TaskRunner('任务',model,lambda deadline:runtime,directory.name,timeout=10)
        self.assertEqual(runner.run(),1)
        self.assertFalse(runtime.starts)
        self.assertEqual([p for p,c in model.calls],['summary'])

    def test_invalid_suffix_cannot_overwrite_accepted_id(self):
        with self.assertRaises(ValueError):review({'action':'modify_plan','stages':[stage('a')]},make_plan(stage('a'),stage('b')),1)
        with self.assertRaises(ValueError):review({'action':'modify_stage','stage':stage('different')},make_plan(),0)
        with self.assertRaises(ValueError):plan(make_plan(stage(allocation={'budget':10**400,'timeout':10})))

    def test_summary_timeout_is_bounded_and_not_retried(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        class SlowSummary(Model):
            def request(self,purpose,payload,images,timeout):
                if purpose=='summary':time.sleep(.15);return {'summary':'late'}
                return super().request(purpose,payload,images,timeout)
        runtime=Runtime();model=SlowSummary([make_plan(),{'action':'accept'}])
        runner=TaskRunner('任务',model,lambda deadline:runtime,temporary.name,summary_timeout=.02)
        self.assertEqual(runner.run(),0)
        self.assertEqual(runner.summary_calls,1)
        value=json.loads((Path(temporary.name)/'summary.json').read_text())
        self.assertEqual(value['source'],'local_fallback')

    def test_missing_images_does_not_skip_summary(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        runtime=Runtime()
        runtime.images=lambda: (_ for _ in ()).throw(OSError('camera unavailable'))
        model=Model([make_plan(),{'action':'accept'}])
        runner=TaskRunner('任务',model,lambda deadline:runtime,temporary.name)
        self.assertEqual(runner.run(),0)
        self.assertEqual(runner.summary_calls,1)

    def test_interrupt_still_routes_to_one_summary(self):
        runner,model,runtime,root,result=self.execute([KeyboardInterrupt()])
        self.assertEqual(result,130)
        self.assertEqual([p for p,c in model.calls],['plan','summary'])


if __name__=='__main__':unittest.main()
