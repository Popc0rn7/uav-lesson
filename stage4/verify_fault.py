"""PC: explicit simulator-only fault tests; own a fresh run, never a model service."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from stage4 import runtime
from stage4.contracts import atomic_json


class SlowAPI(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        self.server.request_started.set()
        time.sleep(3)
        data=dict(action=dict(fwd=1.,down=0.,yaw=0.),stop=False,prompt='fault fixture',raw_output='20 49 49',elapsed_seconds=3.)
        self.send_response(200); self.end_headers()
        try: self.wfile.write(json.dumps(data).encode())
        except BrokenPipeError: pass


def signal_node(state,module,signal):
    runtime.host.owned_ros(state)
    script="""import os,signal,sys
from pathlib import Path
matches=[]
for path in Path('/proc').iterdir():
    if not path.name.isdigit(): continue
    try: args=(path/'cmdline').read_bytes().split(b'\\0')
    except OSError: continue
    if b'-m' in args and sys.argv[1].encode() in args: matches.append(int(path.name))
if len(matches)!=1: raise RuntimeError('Expected exactly one matching owned node: '+str(matches))
os.kill(matches[0],int(sys.argv[2]))
"""
    runtime.host.command('docker','exec',state['ros_container'],'python3','-c',script,module,str(signal))


def run(case,config,directory):
    import signal
    server=None
    if case in ('api-timeout','cancel'):
        server=ThreadingHTTPServer(('127.0.0.1',0),SlowAPI)
        server.request_started=threading.Event()
        threading.Thread(target=server.serve_forever,daemon=True).start()
        os.environ['AEROVLA_API_URL']=f'http://127.0.0.1:{server.server_port}/infer'
        os.environ['AEROVLA_API_TIMEOUT_S']='0.5' if case=='api-timeout' else '10'
    state=None; resumed=False; injected=False; initial_armed=False
    try:
        with runtime.host.management_lock(directory,'up'):
            state_path=directory/'state.json'
            if state_path.exists() and runtime.read(state_path)['phase']!='stopped':
                raise RuntimeError('Fault tests require a fresh run; inspect/land/down the existing instance first')
            runtime.start(config,directory)
        state=runtime.read(directory/'state.json'); run_dir=Path(state['run_dir'])
        atomic_json(run_dir/'start.json',dict(mode='api' if server else 'fixed'))
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            c=runtime.fresh(run_dir/'control.json')
            initial_armed=initial_armed or c.get('armed',False)
            if case=='cancel' and server.request_started.is_set() and not injected:
                runtime.host.request_land(state); injected=True
            elif case in ('camera','control') and c.get('mode')=='move' and not injected:
                signal_node(state,'stage4.sensors' if case=='camera' else 'stage4.control',
                            signal.SIGSTOP if case=='camera' else signal.SIGKILL)
                injected=True
            if case=='camera' and injected and c.get('mode')=='land' and not resumed:
                signal_node(state,'stage4.sensors',signal.SIGCONT); resumed=True
            if case=='control' and injected:
                # No host land command here: prove PX4's own loss fallback.
                result=runtime.host.px4(state,'listener','vehicle_status').stdout
                if initial_armed and 'arming_state: 1' in result:
                    evidence=dict(case=case,passed=True,disarmed_confirmed=True,
                                  scope='Control killed; no host Land issued before disarm',vehicle_status=result)
                    atomic_json(run_dir/'fault-report.json',evidence); return evidence
            report_path=run_dir/'report.json'
            if report_path.exists():
                report=runtime.read(report_path)
                if case=='cancel': time.sleep(3.2)  # Allow delayed HTTP response to arrive.
                after=runtime.read(report_path)
                expected={'api-timeout':'TimeoutError','camera':'camera observation timeout','cancel':'operator requested landing'}[case]
                passed=bool(report['disarmed_confirmed'] and expected in report['reason'] and
                            (case!='cancel' or (report['steps']==0 and after['steps']==0)))
                evidence=dict(case=case,passed=passed,report=after)
                atomic_json(run_dir/'fault-report.json',evidence)
                if not passed: raise RuntimeError('Unexpected fault outcome: '+str(evidence))
                return evidence
            time.sleep(.2)
        raise TimeoutError('Fault verification timeout; inspect state before recovery')
    finally:
        if state:
            if case=='camera' and injected and not resumed:
                try: signal_node(state,'stage4.sensors',signal.SIGCONT)
                except Exception: pass
            # On failure request recovery, but never claim it proves the fallback.
            if not (Path(state['run_dir'])/'fault-report.json').exists():
                try: runtime.host.request_land(state)
                except Exception: pass
            try: runtime.host.shutdown(state,directory)
            except Exception as exc: print('资源保留，请 status/land/stop：',exc,file=sys.stderr)
        if server: server.shutdown(); server.server_close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',choices=('api-timeout','camera','control','cancel'))
    parser.add_argument('--config',type=Path,default=runtime.HERE/'runtime.town05.json')
    parser.add_argument('--state-dir',type=Path,default=ROOT/'artifacts/stage4-faults')
    args=parser.parse_args(); args.state_dir.mkdir(parents=True,exist_ok=True)
    config=runtime.config(args.config); config['no_display']=True
    evidence=run(args.case,config,args.state_dir.resolve())
    print(json.dumps(evidence,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
