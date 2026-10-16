"""飞行复盘必须按测量时间对齐，并排除撞后/非跟踪阶段。"""
from pathlib import Path
import sys
import unittest
import subprocess
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'airsim'))
from review_flight import core_review, interpolate_rows, stats
import runtime


class ReviewTests(unittest.TestCase):
    def test_measurement_time_interpolation_and_gap_rejection(self):
        rows = [dict(sim_s=10.,p=[0,0,0]),dict(sim_s=10.08,p=[.8,0,0])]
        self.assertAlmostEqual(interpolate_rows(rows,10.04)[0],.4)
        self.assertIsNone(interpolate_rows(rows,9.99))
        self.assertIsNone(interpolate_rows(rows,10.09))
        self.assertIsNone(interpolate_rows(rows,10.04,max_gap=.05))

    def test_only_pre_collision_tracking_and_unique_measurements(self):
        def row(t,mode,p):
            return dict(sim_s=t,control=mode,p=[p,0,0],v=[1,0,0],odom_age_s=.01)
        rows = [row(10,'takeoff',100),row(11,'track:',0),row(11,'track:',0),
                row(11.05,'track:',.05),row(11.1,'track:',99),row(11.15,'land:',100)]
        report = dict(summary=dict(collision=True,contacts=[dict(data=dict(time_stamp=11075000000))]),
                      records=rows,references=[dict(kind='sent',sim_s=11,p=[0,0,0]),
                                               dict(kind='sent',sim_s=11.1,p=[.1,0,0])])
        result = core_review(report)
        self.assertEqual(result['telemetry']['unique_tracking_samples'],2)
        self.assertLess(result['telemetry']['aligned_sent_position_error_m']['maximum'],1e-9)
        self.assertAlmostEqual(result['tracking_intervals_s'][-1][1],11.075)

    def test_legacy_report_does_not_claim_aligned_tracking(self):
        result = core_review(dict(summary={},records=[dict(sim_s=10,control='track:',p=[1,0,0],v=[0,0,0],tracking_error_m=100)]))
        self.assertIsNone(result['telemetry']['aligned_sent_position_error_m'])
        self.assertTrue(result['limitations'])

    def test_non_finite_metrics_cannot_be_reported_as_pass(self):
        self.assertIsNone(stats([float('nan'),float('inf')]))
        self.assertEqual(stats([1,2,float('nan')])['samples'],2)

    def test_failed_flight_is_reviewed_and_keeps_failure(self):
        state = dict(ros_container='owned',run_dir='/tmp/run',config={})
        flight = subprocess.CompletedProcess(['flight'],1,'报告：/run/airsim/fly-1.json\n','')
        analysis = subprocess.CompletedProcess(['review'],0,'复盘完成','')
        with patch.object(runtime,'owned_ros',return_value={'State':{'Running':True}}), \
                patch.object(runtime,'command',side_effect=[flight,analysis]) as command:
            with self.assertRaises(subprocess.CalledProcessError) as error:
                runtime.ros_action(state,'fly')
            self.assertEqual(error.exception.returncode,1)
            self.assertIn('复盘完成',error.exception.stdout)
            self.assertEqual(command.call_count,2)

    def test_review_timeout_does_not_turn_success_into_failure(self):
        state = dict(ros_container='owned',run_dir='/tmp/run',config={})
        flight = subprocess.CompletedProcess(['flight'],0,'报告：/run/airsim/fly-1.json\n','')
        with patch.object(runtime,'owned_ros',return_value={'State':{'Running':True}}), \
                patch.object(runtime,'command',side_effect=[flight,subprocess.TimeoutExpired('review',180)]):
            result = runtime.ros_action(state,'fly')
            self.assertEqual(result.returncode,0)
            self.assertIn('复盘失败',result.stdout)


if __name__ == '__main__': unittest.main()
