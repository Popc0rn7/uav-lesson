"""Read-only PC flight console; no ROS, model, or web framework dependency."""
import argparse
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import time
import re
from urllib.parse import urlsplit, parse_qs


def load(path):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return {}


def snapshot(directory):
    state = load(directory/'state.json')
    run = Path(state['run_dir']) if state.get('run_dir') else None
    if run is None: return dict(phase='waiting', stale=True)
    control = load(run/'control.json'); task = load(run/'task.json')
    last = {}; count = 0
    try:
        for line in (run/'inference.jsonl').read_text().splitlines():
            try: last = json.loads(line); count += 1
            except ValueError: pass
    except OSError: pass
    origin = load(run/'origin.json').get('px4_origin_ned')
    position = control.get('position_ned')
    world = ([s+p-o for s,p,o in zip(task['spawn_ned_m'], position, origin)]
             if position is not None and origin is not None else None)
    observations = run/'observations'
    steps = sorted((p for p in observations.iterdir() if p.is_dir() and p.name.isdigit()),
                   key=lambda p:int(p.name)) if observations.exists() else []
    observation = load(run/'observation.json')
    if not observation:
        for step in reversed(steps):
            observation=load(step/'input.json')
            if observation:
                observation.setdefault('step',int(step.name)); break
    # Never pair a previous action/prompt with a new pending observation.
    if not observation or last.get('step')!=observation.get('step'): last={}
    age = time.time()-control.get('wall_time',0)
    return dict(phase=state.get('phase'),run_id=run.name,control=control,
                sensors=load(run/'sensors.json'),report=load(run/'report.json'),
                task=task,inference=last,inference_count=count,observation=observation,
                stale=age>2,age_s=age,position_world_ned=world,
                observation_distance_m=math.dist(observation['estimated_world_ned'],task['target_ned_m'])
                    if observation.get('estimated_world_ned') is not None else None,
                elapsed_seconds=control.get('wall_elapsed_s',0.) if not load(run/'report.json') else load(run/'report.json').get('wall_seconds'),
                distance_m=math.dist(world,task['target_ned_m']) if world is not None else None,
                speed_m_s=math.hypot(*control.get('velocity_ned',[0,0,0])))


def serve(directory, host, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            url=urlsplit(self.path); path=url.path
            content_type='application/json'; status=200
            if path=='/': body=Path(__file__).with_name('webui.html').read_bytes(); content_type='text/html; charset=utf-8'
            elif path=='/webui.css': body=Path(__file__).with_name('webui.css').read_bytes(); content_type='text/css'
            elif path=='/api/state': body=json.dumps(snapshot(directory),ensure_ascii=False).encode()
            elif path in ('/observation/front','/observation/down'):
                query=parse_qs(url.query); run=query.get('run',[''])[0]; step=query.get('step',[''])[0]
                if not re.fullmatch(r'[a-zA-Z0-9_-]+',run) or not re.fullmatch(r'[0-9]+',step):
                    status=400; body=b'Invalid observation'
                else:
                    image=directory/run/'observations'/step/f'{path.rsplit("/",1)[1]}.png'
                    try: body=image.read_bytes()
                    except OSError: body=b''; status=404
                    content_type='image/png'
            elif path in ('/camera/front','/camera/down'):
                state=load(directory/'state.json'); run=Path(state['run_dir']) if state.get('run_dir') else None
                image=run/'webui'/f'{path.rsplit("/",1)[1]}.jpg' if run else None
                try: body=image.read_bytes() if image else b''
                except OSError: body=b''
                content_type='image/jpeg'
                if not body: status=404
            else: status=404; body=b'Not found'
            self.send_response(status); self.send_header('Content-Type',content_type)
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
    server=ThreadingHTTPServer((host,port),Handler)
    print(f'Stage 4 WebUI: http://{host}:{port}',flush=True)
    try: server.serve_forever()
    finally: server.server_close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',type=Path,default=Path(__file__).resolve().parents[1]/'artifacts/stage4-runtime')
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8080)
    args=parser.parse_args(); serve(args.state_dir,args.host,args.port)


if __name__=='__main__': main()
