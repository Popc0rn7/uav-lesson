"""仪表盘单位、失流显示、统计边界、实时转发和只读锁语义。"""
import io
import math
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'airsim'))
from dashboard import Dashboard,clean
import runtime


class DashboardTests(unittest.TestCase):
    def snapshot(self):
        return dict(odom=dict(stamp=10.05,p=[.5,0,2],v=[3,4,0]),reference=dict(v=[0,0,6]),
                    ages=dict(odom=.01,sent=.02,vehicle=.1,task=.1,control=.1),vehicle='Disarmed / Offboard',
                    task='failed: requested landing; waypoint=8/8',control='idle: local_ready',configured_speed=8.)

    def test_units_and_stale_values_cannot_look_like_zero_speed(self):
        ui=Dashboard();ui.reference(10,[0,0,2]);ui.reference(10.1,[1,0,2]);s=self.snapshot()
        lines='\n'.join(ui.lines(s,ui.started+1))
        self.assertIn('实际速度 5.00 m/s',lines);self.assertIn('下发参考 6.00 m/s',lines)
        self.assertIn('同刻误差 0.000 m',lines)
        s['ages']['odom']=1.;lines='\n'.join(ui.lines(s,ui.started+2))
        self.assertIn('实际速度 --',lines);self.assertNotIn('实际速度 0.00',lines)
        self.assertIn('失流',lines)

    def test_mean_uses_unique_measurement_time_and_skips_gaps_and_landing(self):
        ui=Dashboard()
        for t,v,track in [(1.,2.,True),(1.,9.,True),(1.1,4.,True),(1.2,50.,False),(10.,6.,True)]:
            ui.odometry(t,[0,0,0],[v,0,0],track)
        m=ui.metrics();self.assertEqual(m['tracking_peak_speed_m_s'],6.)
        self.assertAlmostEqual(m['tracking_mean_speed_m_s'],3.)
        self.assertAlmostEqual(m['tracking_sim_seconds'],.1)
        self.assertEqual(m['tracking_unique_odom_samples'],3)

    def test_alignment_never_extrapolates_or_crosses_loss(self):
        ui=Dashboard();ui.reference(1,[0,0,0]);ui.reference(1.2,[1,0,0])
        self.assertIsNone(ui.aligned_error(1.1,[.5,0,0]))
        self.assertIsNone(ui.aligned_error(.9,[0,0,0]))
        ui.reference(.5,[0,0,0]);self.assertEqual(len(ui.refs),1)

    def test_plain_is_readable_and_ansi_restores_cursor_with_final_frame(self):
        for mode in ('plain','ansi'):
            out=io.StringIO();ui=Dashboard(mode,stream=out,previous=dict(success=False,max_speed_m_s=7.6,reason='timeout'))
            ui.render(self.snapshot(),force=True);ui.close();text=out.getvalue()
            self.assertIn('上轮报告 失败',text);self.assertIn('7.60 m/s',text)
            self.assertIn('最终遥测快照',text)
            if mode=='ansi':self.assertIn('\x1b[?25h\x1b[?1049l',text)
            else:self.assertNotIn('\x1b',text)
        self.assertNotIn('\x1b',clean('untrusted\x1b[2J\ntext'))

    def test_terminal_failure_does_not_interrupt_control_observer(self):
        class Closed:
            def write(self,text):raise BrokenPipeError()
        ui=Dashboard('ansi',stream=Closed());ui.render(self.snapshot(),force=True);ui.close()
        self.assertEqual(ui.mode,'off')

    def test_stream_reaches_console_before_child_can_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'received'
            class Console(io.StringIO):
                def write(self,text):
                    if '实时' in text:marker.touch()
                    return super().write(text)
            console=Console()
            script="import sys,time;from pathlib import Path;print('实时',flush=True);p=Path(sys.argv[1]);end=time.monotonic()+2\nwhile not p.exists() and time.monotonic()<end:time.sleep(.01)\nassert p.exists(),'buffered until completion';print('done',flush=True)"
            with patch('runtime.sys.stdout',console):result=runtime.streaming_command(sys.executable,'-c',script,str(marker),timeout=4)
            self.assertEqual(result.returncode,0);self.assertIn('实时\ndone',result.stdout)
            self.assertEqual(console.getvalue(),result.stdout)

    def test_dashboard_never_holds_task_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with runtime.management_lock(root,'dashboard'):
                with runtime.management_lock(root,'task'):
                    with runtime.management_lock(root,'dashboard'):pass

    def test_streamed_failure_still_reviews_report_and_keeps_nonzero_result(self):
        flight=subprocess.CompletedProcess(['flight'],1,'\x1b[H仪表盘\n报告：/run/airsim/fly-1.json\n','')
        review=subprocess.CompletedProcess(['review'],0,'复盘完成\n','');out=io.StringIO()
        state=dict(ros_container='owned',run_dir='/tmp/run',config={})
        with patch.object(runtime,'owned_ros',return_value={'State':{'Running':True}}), \
             patch.object(runtime,'streaming_command',return_value=flight), \
             patch.object(runtime,'command',return_value=review) as command,patch('runtime.sys.stdout',out):
            with self.assertRaises(subprocess.CalledProcessError) as error:runtime.ros_action(state,'fly',stream=True,dashboard='plain')
        self.assertEqual(error.exception.returncode,1)
        self.assertTrue(error.exception.streamed)
        self.assertIn('报告：',error.exception.stdout)
        self.assertEqual(out.getvalue().count('复盘完成'),1)
        command.assert_called_once()


if __name__=='__main__':unittest.main()
