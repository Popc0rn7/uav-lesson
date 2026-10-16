"""计算计时与跨主机点云时长：验证时钟偏移不会污染统计。"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('profile_analysis',ROOT/'stage3/board/analyse_profile.py')
analysis=importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class ProfileTests(unittest.TestCase):
    def test_roundtrip_cancels_host_clock_offset_and_cpu_separates_wait(self):
        with tempfile.TemporaryDirectory() as temporary:
            run=Path(temporary)
            def write(name,rows):
                p=run/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            (run/'fly-task-1.json').write_text(json.dumps(dict(summary=dict(success=False))))
            write('board-logs/profile/planner.jsonl',[
                dict(scope='ReplanOnce',wall_ns=20000000,thread_cpu_ns=5000000,process_cpu_ns=8000000)])
            # Absolute board and PC clocks differ by thousands of seconds.
            board=10**12;pc=8*10**12
            write('board-logs/profile/lidar.jsonl',[
                dict(kind='raw_received',stamp=42,mono_ns=board),
                dict(kind='cloud_publish',stamp=42,mono_ns=board+10000000,
                     process_wall_s=.008,process_cpu_s=.007,queue_wait_s=.002)])
            write('profile/raw.jsonl',[
                dict(kind='raw_publish',stamp=42,mono_ns=pc,rpc_wall_s=.001)])
            write('observer-profile.jsonl',[
                dict(kind='cloud_observed',source_sim_ns=42,mono_ns=pc+30000000)])
            write('board-logs/profile/control.jsonl',[])
            result=analysis.analyse(run)
            self.assertAlmostEqual(result['cloud_pipeline']['pc_roundtrip_s']['median'],.03)
            self.assertAlmostEqual(result['cloud_pipeline']['board_residence_s']['median'],.01)
            self.assertAlmostEqual(result['cloud_pipeline']['transport_and_unmeasured_callbacks_s']['median'],.02)
            self.assertAlmostEqual(result['computation']['ReplanOnce']['non_cpu_s']['median'],.015)
            self.assertFalse(result['flight_result']['success'])

    def test_missing_measurements_are_not_reported_as_zero_latency(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):analysis.analyse(Path(temporary))


if __name__=='__main__':unittest.main()
