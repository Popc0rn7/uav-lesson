"""诊断隔离、确定性轨迹和 HIL 精确配对边界。"""
import contextlib
import io
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]/'airsim'
sys.path.insert(0,str(HERE/'diagnostics'))
sys.path.insert(0,str(HERE))
from response_profile import load,sample,segments
from hil import Reassembly,decode
from diagnose import prepare_response,response_up
from analyse import analyse
from unittest.mock import patch


class DiagnosticsTests(unittest.TestCase):
    def test_profile_derivatives_and_continuous_boundaries(self):
        c=load(HERE/'diagnostics/response_profile.json')
        t=0
        for segment in segments(c):
            t+=segment[2]
            before=sample(c,t-1e-7);after=sample(c,t+1e-7)
            for field in (1,2,3):self.assertLess(math.dist(before[field],after[field]),1e-5)
        for t in (1.2,8.4,26.1,31.2):
            left=sample(c,t-1e-5);right=sample(c,t+1e-5);middle=sample(c,t)
            for pos,derivative in ((1,2),(2,3)):
                numeric=[(b-a)/2e-5 for a,b in zip(left[pos],right[pos])]
                self.assertLess(math.dist(numeric,middle[derivative]),1e-6)
        self.assertTrue(sample(c,t+200)[4])

    def test_profile_rejects_unsafe_demand(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'p.json';c=load(HERE/'diagnostics/response_profile.json')
            c['line_duration_s']=.1;path.write_text(json.dumps(c))
            with self.assertRaises(ValueError):load(path)

    def test_tcp_reorder_overlap_and_wrap(self):
        s=Reassembly();self.assertEqual(s.feed(99,b'',True),b'')
        self.assertEqual(s.feed(103,b'def'),b'')
        self.assertEqual(s.feed(100,b'abc'),b'abcdef')
        self.assertEqual(s.feed(102,b'cdefg'),b'g')
        self.assertGreater(s.duplicates,0)
        s=Reassembly();self.assertEqual(s.feed(0xfffffffe,b'abcd'),b'abcd')
        self.assertEqual(s.feed(2,b'ef'),b'ef')

    def test_hil_pairs_only_echoed_stamp_across_tcp_segments(self):
        from pymavlink.dialects.v20 import common
        mav=common.MAVLink(None)
        sensor=mav.hil_sensor_encode(100,*([0.]*13),0).pack(mav)
        actuator=mav.hil_actuator_controls_encode(100,[0.]*16,0,0).pack(mav)
        wrong=mav.hil_actuator_controls_encode(101,[0.]*16,0,0).pack(mav)
        def frame(sport,dport,seq,payload):
            tcp=struct.pack('!HHIIBBHHH',sport,dport,seq,0,0x50,0x18,65535,0,0)
            ip=struct.pack('!BBHHHBBH4s4s',0x45,0,40+len(payload),0,0,64,6,0,b'\x7f\0\0\1',b'\x7f\0\0\1')
            return b'\0'*12+b'\x08\x00'+ip+tcp+payload
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'hil.pcap'
            with path.open('wb') as out:
                out.write(struct.pack('<IHHIIII',0xa1b23c4d,2,4,0,0,65535,1))
                for ns,sport,dport,seq,data in [(0,4560,3000,10,sensor[:9]),(100,4560,3000,19,sensor[9:]),
                        (200100,3000,4560,50,wrong+actuator),(300100,3000,4560,50,wrong+actuator)]:
                    p=frame(sport,dport,seq,data);out.write(struct.pack('<IIII',1,ns,len(p),len(p))+p)
            result=decode(path)
            self.assertEqual(len(result['pairs']),1)
            self.assertEqual(result['pairs'][0]['sim_us'],100)
            self.assertAlmostEqual(result['pairs'][0]['sensor_to_reply_wall_ms'],.2)
            self.assertGreater(result['tcp_duplicates'],0)

    def test_snapshot_only_and_single_factor(self):
        paths=[HERE/'runtime.super.json',HERE/'settings.json',HERE/'task.low.json']
        before={p:p.read_bytes() for p in paths}
        with tempfile.TemporaryDirectory() as tmp:
            configs=[];tasks=[]
            for load_profile in ('baseline','render-low','lidar-low'):
                c=prepare_response(paths[0],HERE/'diagnostics/response_profile.json',load_profile,Path(tmp)/load_profile)
                configs.append(c);tasks.append(json.loads(Path(c['super_task']).read_text()))
            self.assertEqual(len({c['container'] for c in configs}),3)
            for c in configs:self.assertTrue(c['diagnostics'])
            for task in tasks:task.pop('name')
            self.assertEqual(tasks[0],tasks[1])
            tasks[2]['lidar']['settings']['PointsPerSecond']=tasks[0]['lidar']['settings']['PointsPerSecond']
            self.assertEqual(tasks[0],tasks[2])
        self.assertEqual(before,{p:p.read_bytes() for p in paths})

    def test_busy_port_cannot_create_or_stop_resources(self):
        with patch('diagnose.runtime.check_ports',side_effect=RuntimeError('busy')),patch('diagnose.prepare_response') as prepare:
            with self.assertRaisesRegex(RuntimeError,'busy'):response_up(None,None,'baseline')
            prepare.assert_not_called()

    def test_stationary_references_are_not_invented_matches(self):
        def row(kind,t,p):return dict(kind=kind,mono_ns=t,source_sim_ns=t,observed_clock_ns=t,p=[p,0,0],v=[0,0,0],a=[0,0,0])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);rows=[row('planner',1,0),row('planner',2,0),row('adapter',3,0),row('planner',5,1),row('adapter',4,1)]
            (path/'ros.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            with contextlib.redirect_stdout(io.StringIO()):result=analyse(path)
            self.assertEqual(result['planner_adapter']['unique_signature_pairs'],1)
            self.assertLess(result['planner_adapter']['observer_delta_wall_ms']['maximum'],0)


if __name__=='__main__':unittest.main()
