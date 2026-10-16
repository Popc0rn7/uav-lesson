"""几何与配置回归：验证采样配准、FRD/FLU 和交接路线原点。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
from scipy.spatial.transform import Rotation

HERE = Path(__file__).resolve().parents[1] / 'airsim'
sys.path.insert(0, str(HERE))
from geometry import interpolate, register
from task_config import apply_settings, load_task
from planner_config import generate


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.task = load_task(HERE / 'task.low.json')

    def test_sampling_interpolates_position_and_rotation(self):
        q0 = Rotation.from_euler('z', 0, degrees=True).as_quat()
        q1 = Rotation.from_euler('z', 90, degrees=True).as_quat()
        pose = interpolate([(1.,[0,0,0],q0),(1.04,[4,0,0],q1)],1.02)
        np.testing.assert_allclose(pose[0],[2,0,0])
        np.testing.assert_allclose(pose[1] @ [1,0,0],[2**-.5,2**-.5,0],atol=1e-8)
        self.assertIsNone(interpolate([(1.,[0,0,0],q0),(1.2,[4,0,0],q1)],1.1))
        self.assertIsNone(interpolate([(1.,[0,0,0],q0),(1.04,[4,0,0],q1)],.99))

    def test_sensor_extrinsic_and_body_axes(self):
        lidar = dict(self.task['lidar'], position_frd_m=[.2,.3,-.4], rotation_rpy_deg=[0,0,90])
        cloud = register([[1,0,0]], (np.array([10,20,2]),np.eye(3)),lidar)
        np.testing.assert_allclose(cloud,[[10.2,18.7,2.4]],atol=1e-6)

    def test_filter_and_voxel_preserve_obstacles(self):
        cloud = register([[1,0,0],[1.01,0,0],[2,0,0],[.1,0,0],[50,0,0],[float('nan'),0,0]],
                         (np.zeros(3),np.eye(3)),self.task['lidar'])
        self.assertEqual(len(cloud),2)
        np.testing.assert_allclose(cloud[:,0],[1,2])

    def test_forest_route_is_relative_to_spawn(self):
        task = load_task(HERE / 'task.forest8.json')
        np.testing.assert_allclose(task['waypoints_enu_m'][-1],[-37.57,231.76,6])
        settings = apply_settings({'Vehicles':{'PX4':{'VehicleType':'PX4Multirotor'}}},task)
        self.assertEqual(settings['Vehicles']['PX4']['X'],42.60)
        self.assertEqual(settings['Vehicles']['PX4']['Sensors']['Lidar1']['DataFrame'],'SensorLocalFrame')

    def test_planner_and_control_share_limits(self):
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'planner.yaml'
            generate(HERE/'task.low.json',output)
            config = yaml.safe_load(output.read_text())
            self.assertEqual(config['traj_opt']['boundary']['max_vel'],self.task['speed_m_s'])
            self.assertEqual(config['traj_opt']['boundary']['max_acc'],self.task['max_acc_m_s2'])

    def test_speed_range_keeps_acceleration_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'task.json'
            for speed,acceleration,valid in ((10,8,True),(12,8,True),(15,8,True),(15.1,8,False),(15,8.1,False)):
                path.write_text(json.dumps(dict(self.task,speed_m_s=speed,max_acc_m_s2=acceleration)))
                if valid:self.assertEqual(load_task(path)['speed_m_s'],speed)
                else:
                    with self.assertRaises(ValueError):load_task(path)

    def test_lidar_loss_policy_is_explicit_and_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'task.json'
            for action in ('land', 'observe'):
                path.write_text(json.dumps(dict(self.task,lidar_loss_action=action)))
                self.assertEqual(load_task(path)['lidar_loss_action'],action)
            path.write_text(json.dumps(dict(self.task,lidar_loss_action='ignore-typo')))
            with self.assertRaises(ValueError):load_task(path)

    def test_reject_route_outside_bounds(self):
        task = dict(self.task,waypoints_enu_m=[[100,0,2]])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.json'
            path.write_text(json.dumps(task))
            with self.assertRaisesRegex(ValueError,'边界'):
                load_task(path)

    def test_ab_experiment_policies_and_validation(self):
        for filename in ('task.forest10-ab.json','task.forest5-ab-observe.json'):
            task=load_task(HERE/filename)
            self.assertEqual(task['trajectory_limits_action'],'observe')
            self.assertEqual(task['lidar_loss_action'],'observe')
        self.assertEqual(self.task['trajectory_limits_action'],'land')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'task.json'
            path.write_text(json.dumps(dict(self.task,trajectory_limits_action='typo')))
            with self.assertRaisesRegex(ValueError,'trajectory_limits_action'):
                load_task(path)


if __name__ == '__main__':
    unittest.main()
