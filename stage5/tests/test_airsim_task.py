"""离线验证起飞屏障、部分启动恢复、坐标与任务能力；不连接设备/模型。"""
import json
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_contracts import stage
from stage5.airsim.geometry import follow_goal, pose_at_capture, camera_point_ned
from stage5.airsim.perception import choose_target
from stage5.airsim.task import await_hover
from stage5.airsim import task, preflight


class TaskContracts(unittest.TestCase):
    def test_third_tracking_frame_remains_json_serializable(self):
        from collections import deque
        import threading
        import time
        from stage5.airsim.perception import AirSimPerception
        sensor = AirSimPerception.__new__(AirSimPerception)
        sensor.stop = threading.Event(); sensor.lock = threading.Lock()
        sensor.history = deque(maxlen=10); sensor.velocity = np.zeros(3)
        sensor.generation = 1; sensor.text = 'pickup'; sensor.config = {'STAGE5_RGB_URL': '', 'STAGE5_DEPTH_URL': ''}
        sensor.filter_threshold = .2; sensor.model = {'depth': {'cy': 0, 'fy': 320}}
        sensor.publish_request_preview = Mock(); sensor.clearance = Mock(return_value=20.)
        sensor.dino = Mock(); sensor.dino.detect.return_value = ({'detections': [], 'width': 640, 'height': 360}, 0)
        count = 0
        def frames(*args):
            nonlocal count
            count += 1
            if count == 3: sensor.stop.set()
            meta = {'sim_time': count*.2, 'received': time.monotonic(), 'px4_pose': {'max_skew_s': 0}}
            return (meta, b''), (meta, b'')
        candidate = {'status': 'estimated_surface', 'score': .9, 'box_xyxy': [0, 0, 10, 10],
                     'depth_box_xyxy': [0, 0, 10, 10], 'position_m': [5, 0, 0]}
        with patch('stage5.airsim.perception.filter_candidates', return_value=([], [{'label': 'pickup', 'score': .9, 'accepted': True}])), \
             patch('stage5.airsim.perception.paired_frames', side_effect=frames), \
             patch('stage5.airsim.perception.camera_png', side_effect=lambda url, timeout, rgb: (b'png', rgb[0])), \
             patch('stage5.airsim.perception.fuse', return_value={'targets': [candidate]}), \
             patch('stage5.airsim.perception.camera_point_ned', side_effect=lambda *args: np.array([count*.2, 0., 0.])), \
             patch('stage5.airsim.perception.build', return_value={'motion_candidates': {}}):
            sensor.worker()
        self.assertIsNone(sensor.error)
        self.assertEqual(len(sensor.history), 3)
        self.assertEqual(len(sensor.latest['observation_window']), 3)
        self.assertTrue(sensor.latest['observation_window'][0]['tracking_available'])
        self.assertIs(type(sensor.latest['tracking']['direction_confirmed']), bool)
        json.dumps(sensor.latest, allow_nan=False)

    def test_only_explicit_out_of_range_has_control_proxy(self):
        from stage5.airsim.perception import control_point
        model = {'depth': dict(cx=320, cy=200, fx=320, fy=320)}
        target = dict(status='too_far', score=.9, box_xyxy=[300, 180, 340, 220],
                      depth_box_xyxy=[300, 180, 340, 220], distance_lower_bound_m=20, position_m=None)
        self.assertEqual(choose_target([target]), target)
        point, proxy = control_point(target, model)
        self.assertTrue(proxy)
        np.testing.assert_allclose(point, [20, 0, 0])
        self.assertIsNone(target['position_m'])  # 原始测量保持未知，代理单独标记。
        for status in ('insufficient_depth', 'mixed_depth', 'mostly_too_far', 'unsynchronized'):
            invalid = {**target, 'status': status}
            self.assertIsNone(choose_target([invalid]))
            with self.assertRaises(ValueError): control_point(invalid, model)

    def test_ned_left_and_rear_offsets(self):
        base = dict(horizontal_distance_m=6, above_m=3)
        np.testing.assert_allclose(follow_goal([10, 20, 0], [1, 0], {**base, 'following_mode': 'left_alongside'}), [10, 14, -3])
        np.testing.assert_allclose(follow_goal([10, 20, 0], [1, 0], {**base, 'following_mode': 'rear_above'}), [4, 20, -3])
        np.testing.assert_allclose(follow_goal([10, 20, 0], [1, 0], {**base, 'following_mode': 'directly_overhead'}), [10, 20, -3])

    def test_capture_pose_rejects_stale_or_missing_estimates(self):
        pos = [(10., [1, 2, 3])]; att = [(10.01, [1, 0, 0, 0])]
        self.assertIsNone(pose_at_capture(pos, [], 10))
        self.assertIsNone(pose_at_capture(pos, att, 10.2))
        self.assertEqual(pose_at_capture(pos, att, 10)['p'], [1, 2, 3])
        model = dict(position_body_frd_m=[.5, 0, .1], rotation_camera_frd_to_body_frd=np.eye(3).tolist())
        np.testing.assert_allclose(camera_point_ned([8, 2, 1], dict(p=[10, 20, -3], q=[1, 0, 0, 0]), model), [18.5, 18, -3.9])

    def test_follow_schema_requires_mode_and_zero_offset_for_overhead(self):
        value = dict(id='follow', goal='follow', dino_text='a pickup truck.', completion_criteria='valid following',
            failure_criteria='lost', allocation={'budget': 30, 'timeout': 55}, allowed_skills=['hold_course', 'brake'],
            skill='follow_vehicle', horizontal_distance_m=8, above_m=2, duration_s=10)
        with self.assertRaises(ValueError):
            stage(value)
        self.assertEqual(stage({**value, 'following_mode': 'rear_above'})['horizontal_distance_m'], 8)
        with self.assertRaises(ValueError):
            stage({**value, 'following_mode': 'directly_overhead'})

    def test_review_without_echo_fields_advances_without_budget_repair(self):
        from stage5.airsim.mission_runtime import AirSimQwenAgent
        from qwen_agent import QwenAgent
        from task_runner import TaskRunner
        from test_task_runner import Runtime,stage as make_stage,make_plan
        agent=AirSimQwenAgent.__new__(AirSimQwenAgent);agent.config={}
        find=make_stage(id='find',skill='observe_target',allowed_skills=['brake','reacquire'])
        follow=make_stage(skill='follow_vehicle',following_mode='rear_above')
        runtime=Runtime(['done','done'])
        responses=[make_plan(find,follow),{'action':'accept'},{'action':'accept'},{'summary':'ok'}]
        with tempfile.TemporaryDirectory() as directory, patch.object(QwenAgent,'request',side_effect=responses):
            runner=TaskRunner('持续跟随',agent,lambda deadline:runtime,directory,budget=3,timeout=10)
            self.assertEqual(runner.run(),0)
            self.assertEqual(runner.calls,3)
            self.assertEqual([v['stage']['id'] for v in runtime.starts],['find','follow'])
            self.assertNotIn('invalid_qwen_result',(Path(directory)/'events.jsonl').read_text())

    def test_airsim_review_must_bind_current_stage_and_attempt(self):
        from stage5.airsim.mission_runtime import AirSimQwenAgent
        from qwen_agent import QwenAgent
        agent=AirSimQwenAgent.__new__(AirSimQwenAgent);agent.config={}
        payload=dict(plan={'stages':[{'id':'find'},{'id':'follow'}]},current_index=1,
                     stage_reports=[{'attempt':2}])
        for response in ({'action':'accept','reviewed_stage_id':'find','reviewed_attempt':1},):
            with patch.object(QwenAgent,'request',return_value=response):
                with self.assertRaisesRegex(ValueError,'验收对象不匹配'):
                    agent.request('review',payload,[],1)
        with patch.object(QwenAgent,'request',return_value={'action':'accept'}):
            bound=agent.request('review',payload,[],1)
            self.assertEqual(bound,dict(action='accept',reviewed_stage_id='follow',reviewed_attempt=2))
        response=dict(action='accept',reviewed_stage_id='follow',reviewed_attempt=2)
        with patch.object(QwenAgent,'request',return_value=response):
            self.assertEqual(agent.request('review',payload,[],1),response)

    def test_continuous_follow_has_no_required_duration(self):
        from test_task_runner import stage as make_stage
        from stage5.airsim.mission_runtime import supported_stage
        value=make_stage(skill='follow_vehicle',following_mode='rear_above',continuous=True,
                         goal='持续跟随黄皮卡',completion_criteria='建立持续跟随',dino_text='a yellow pickup truck.')
        value.pop('duration_s')
        parsed=stage(value)
        supported_stage(parsed,dict(behind_m=8,above_roof_m=2,continuous=True))
        self.assertNotIn('duration_s',parsed)
        with self.assertRaises(ValueError):
            stage({**value,'completion_criteria':'跟随10秒'})

    def test_candidate_does_not_rewrite_fixed_target_or_duration(self):
        from stage5.airsim.mission_runtime import supported_stage
        selected = dict(behind_m=8, above_roof_m=2, duration_s=10)
        value = dict(skill='follow_vehicle', following_mode='rear_above', horizontal_distance_m=8, above_m=2,
                     duration_s=10, dino_text='a pickup truck.', allowed_skills=['hold_course', 'brake', 'scan_yaw'])
        supported_stage(value, selected)
        for bad in ({'duration_s': 60}, {'above_m': 6}, {'following_mode': 'left_alongside'}, {'dino_text': 'a white truck.'}):
            with self.assertRaises(ValueError):
                supported_stage({**value, **bad}, selected)

    def test_static_camera_measurement_uses_relative_pose_and_checks_quaternions(self):
        from stage5.airsim.config import load
        with patch.dict('os.environ', {'AIRSIM_MOUNTAINS': '/tmp/stage5-test/demo/Binaries/Linux/demo-Linux-Shipping'}):
            config = load(Path(__file__).resolve().parents[1]/'airsim/runtime.demo.json')
        q = dict(w_val=1., x_val=0., y_val=0., z_val=0.)
        def v(x, y, z): return dict(x_val=x, y_val=y, z_val=z)
        own = dict(landed_state=0, kinematics_estimated=dict(position=v(10, 20, 4), orientation=q, linear_velocity=v(0, 0, 0)))
        camera = dict(fov=90, pose=dict(position=v(10.46, 20, 4.1), orientation=q))
        def call(config, method, *args):
            if method == 'getMultirotorState': return own
            if method == 'simGetVehiclePose': return own['kinematics_estimated']
            return camera
        with patch.object(task, 'call', side_effect=call):
            model = task.measure_camera(config)
            np.testing.assert_allclose(model['position_body_frd_m'], [.46, 0, .1])
            np.testing.assert_allclose(model['body_center_camera_flu_m'], [-.46, 0, .1])
            camera['pose']['orientation'] = dict(w_val=0, x_val=0, y_val=0, z_val=0)
            with self.assertRaises(ValueError):
                task.measure_camera(config)

    def test_current_target_is_not_vetoed_by_old_box_or_score_margin(self):
        a = dict(status='estimated_surface', score=.8, box_xyxy=[0, 0, 10, 10])
        b = dict(status='estimated_surface', score=.79, box_xyxy=[50, 50, 60, 60])
        self.assertEqual(choose_target([a, b]), a)
        self.assertEqual(choose_target([b]), b)

    def barrier(self, *, moving=False, stale=False, future=True):
        now = [0.]
        flight = Mock(armed=True, mode=4, sub_mode=3, heartbeat_at=0.)
        flight.snapshot.side_effect = lambda: dict(p=np.array([0, 0, -3]), v=np.array([1 if moving else 0, 0, 0]), age=1 if stale else 0)
        flight.poll.side_effect = lambda: setattr(flight, 'heartbeat_at', now[0])
        result = queue.Queue()
        if future:
            result.put((True, True))
        def sleep(value): now[0] += value
        return flight, result, now, sleep

    def test_hover_requires_two_seconds_and_successful_future(self):
        flight, result, now, sleep = self.barrier()
        await_hover(flight, np.zeros(3), 3, result, 5, Mock(), clock=lambda: now[0], sleep=sleep)
        self.assertGreaterEqual(now[0], 2)
        flight.hold.assert_called_once()
        for moving, future in ((True, True), (False, False)):
            flight, result, now, sleep = self.barrier(moving=moving, future=future)
            with self.assertRaises(TimeoutError):
                await_hover(flight, np.zeros(3), 3, result, 3, Mock(), clock=lambda: now[0], sleep=sleep)

    def test_stale_pose_never_passes_hover(self):
        flight, result, now, sleep = self.barrier(stale=True)
        with self.assertRaises(RuntimeError):
            await_hover(flight, np.zeros(3), 3, result, 5, Mock(), clock=lambda: now[0], sleep=sleep)

    def test_dispatch_ack_does_not_cancel_takeoff_before_target_height(self):
        flight, result, now, sleep = self.barrier()
        flight.snapshot.side_effect = lambda: dict(p=np.zeros(3), v=np.zeros(3), age=0)
        with self.assertRaises(TimeoutError):
            await_hover(flight, np.zeros(3), 3, result, 3, Mock(), clock=lambda: now[0], sleep=sleep)
        flight.hold.assert_not_called()

    def test_auto_mode_without_loiter_does_not_pass_hover(self):
        flight, result, now, sleep = self.barrier()
        flight.sub_mode = 6
        with self.assertRaises(TimeoutError):
            await_hover(flight, np.zeros(3), 3, result, 3, Mock(), clock=lambda: now[0], sleep=sleep)

    def test_health_does_not_call_models_when_transport_is_lost(self):
        with patch('stage5.airsim.runtime.inspect', return_value={'ready': False}), patch.object(preflight, 'check_models') as models:
            self.assertFalse(preflight.check({'run_id': 'test'}, {})['ready'])
            models.assert_not_called()

    def test_convoy_stop_failure_still_closes_flight_and_sensor_resources(self):
        from stage5.airsim.mission_runtime import AirSimFlightRuntime
        executor = AirSimFlightRuntime.__new__(AirSimFlightRuntime)
        executor.actor = Mock(); executor.perception = Mock(); executor.flight = Mock(); executor.lease = Mock()
        executor.car_started = False; executor.config = {'STAGE5_BACKEND': 'airsim'}
        executor.stop_convoy = Mock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):
            executor.close()
        executor.flight.hold.assert_called_once()
        executor.flight.close.assert_called_once()
        executor.perception.close.assert_called_once()
        executor.lease.close.assert_called_once()

    def run_partial_start(self, response=None, error=None, hover_error=None):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        state = dict(run_id='test', run_dir=str(root), config=dict(raw_port=8189, rpc_host='127.0.0.1', rpc_port=41451, vehicle_name='Drone1', spawn_yaw_deg=180))
        (root/'state.json').write_text(json.dumps(state))
        flight = Mock(armed=False); flight.snapshot.return_value = dict(p=np.zeros(3))
        flight.poll.side_effect = lambda: setattr(flight, 'armed', True)
        convoy = Mock(); convoy.simStartConvoy.return_value = response; convoy.simStartConvoy.side_effect = error
        convoy.simStopConvoy.return_value = {'ok': True}
        def hover(flight, initial, height, result, timeout, record, cancel=None):
            if hover_error:
                raise hover_error
            record('takeoff_complete')
        patches = [patch.object(task, 'await_hover', side_effect=hover), patch('sys.argv', ['task', 'run', '--state-dir', str(root)]),
            patch.object(task, 'configuration', return_value={}), patch.object(task, 'check', return_value={'ready': True}),
            patch.object(task, 'measure_camera', return_value={}), patch.object(task, 'inspect', return_value={'ready': True}),
            patch.object(task, 'Flight', return_value=flight), patch.object(task, 'ConvoyClient', return_value=convoy),
            patch.object(task, 'px4'), patch.object(task.signal, 'signal')]
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        code = task.main()
        events = [json.loads(line)['event'] for p in root.glob('task-*/bootstrap.jsonl') for line in p.read_text().splitlines()]
        return code, convoy, task.px4, events

    def test_interrupted_model_task_requests_land_through_runtime_recovery(self):
        with patch('task_runner.TaskRunner') as runner, \
                patch('stage5.airsim.mission_runtime.AirSimQwenAgent'), \
                patch('mission_registry.register'),patch.object(task,'request_land') as land:
            runner.return_value.run.return_value=130
            code,convoy,px4,events=self.run_partial_start(response={'ok':True,'started_now':True})
            self.assertEqual(code,130)
            land.assert_called_once()
            self.assertIn('model_task_started',events)

    def test_ambiguous_convoy_start_attempt_is_stopped_and_land_requested(self):
        code, convoy, px4, events = self.run_partial_start(error=TimeoutError())
        self.assertEqual(code, 1)
        convoy.simStopConvoy.assert_called_once()
        self.assertEqual(px4.call_args.args[1:], ('commander', 'land'))
        self.assertLess(events.index('takeoff_dispatched'), events.index('takeoff_complete'))
        self.assertLess(events.index('takeoff_complete'), events.index('convoy_start_requested'))
        self.assertNotIn('model_task_started', events)

    def test_hover_failure_does_not_start_convoy(self):
        code, convoy, px4, events = self.run_partial_start(hover_error=TimeoutError('hover timeout'))
        self.assertEqual(code, 1)
        convoy.simStartConvoy.assert_not_called()
        convoy.simStopConvoy.assert_not_called()
        self.assertEqual(px4.call_args.args[1:], ('commander', 'land'))
        self.assertNotIn('convoy_start_requested', events)

    def test_preexisting_convoy_is_not_stopped(self):
        code, convoy, px4, events = self.run_partial_start(response={'ok': True, 'started_now': False})
        self.assertEqual(code, 1)
        convoy.simStopConvoy.assert_not_called()
        self.assertNotIn('model_task_started', events)


if __name__ == '__main__':
    unittest.main()
