"""PC 本地只读任务灯箱；不连接 PX4、不请求模型。"""
import argparse
import hashlib
import json
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import time

from mission_registry import latest

WEB = Path(__file__).with_name('webui')
AIRSIM_STATE = Path(__file__).resolve().parents[1]/'artifacts/stage5-airsim/state.json'
STATIC_FILES = {
    '/': ('index.html', 'text/html'),
    '/app.js': ('app.js', 'text/javascript'),
    '/style.css': ('style.css', 'text/css'),
}


def read_json(path, fallback=None):
    if path is None:
        return fallback
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def read_events(directory, limit=80):
    """尾部正在追加的半行不应使已有完整事件消失。"""
    if directory is None:
        return []
    try:
        with (directory / 'events.jsonl').open(encoding='utf-8') as stream:
            lines = deque(stream, maxlen=limit)
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def state_packet(directory, follow_latest):
    def read(name, fallback=None):
        return read_json(directory / name if directory else None, fallback)

    state = read('ui.json', {})
    summary = read('summary.json')
    if summary and state:
        state.update(finalized=True, qwen_activity=None)
    return dict(
        state=state,
        events=read_events(directory),
        terminal=read('terminal.json'),
        summary=summary,
        now=time.monotonic(),
        run=directory.name if directory else '等待mission',
        run_id=str(directory) if directory else None,
        follow_latest=follow_latest,
        airsim=airsim_packet() if follow_latest else None,
    )


def airsim_packet(path=None):
    """只读本工作树运行快照；不通过网页发起Docker、RPC或飞行动作。"""
    state = read_json(path or AIRSIM_STATE, {})
    if not state.get('run_dir'):
        return None
    sensor_path = Path(state['run_dir'])/'sensors.json'
    sensors = read_json(sensor_path, {})
    try:
        age = time.time()-sensor_path.stat().st_mtime
    except OSError:
        age = None
    live = state.get('phase') == 'ready' and age is not None and 0 <= age < 2 and sensors.get('healthy', False)
    return dict(run_id=state.get('run_id'), phase=state.get('phase'), live=bool(live),
                snapshot_age_s=age, telemetry=sensors.get('telemetry', {}),
                telemetry_age_s={k:v+max(0,age or 0) for k,v in sensors.get('telemetry_age_s', {}).items()},
                pairs=sensors.get('pairs', 0),
                pair_age_s=(sensors['pair_age_s']+max(0,age or 0)) if sensors.get('pair_age_s') is not None else None,
                error=sensors.get('error'), raw_camera_port=state.get('config', {}).get('raw_port'))


def make_handler(pinned=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_body(self, body, mime, etag=None):
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if etag:
                self.send_header('ETag', etag)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = self.path.split('?', 1)[0]
            if route in STATIC_FILES:
                filename, mime = STATIC_FILES[route]
                self.send_body((WEB / filename).read_bytes(), mime)
                return
            if route not in ('/api/state', '/api/preview'):
                self.send_error(404)
                return

            directory = pinned or latest()
            etag = None
            if route == '/api/state':
                value = state_packet(directory, follow_latest=pinned is None)
            else:
                path = directory/'preview.json' if directory else None
                try:
                    stat = path.stat() if path else None
                except FileNotFoundError:
                    stat = None
                identity = f'{directory}:{stat.st_mtime_ns if stat else 0}:{stat.st_size if stat else 0}'
                etag = '"'+hashlib.sha256(identity.encode()).hexdigest()+'"'
                if self.headers.get('If-None-Match') == etag:
                    self.send_response(304)
                    self.send_header('ETag', etag)
                    self.end_headers()
                    return
                value = dict(
                    preview=read_json(directory / 'preview.json', {}) if directory else {},
                    run_id=str(directory) if directory else None,
                )
            self.send_body(json.dumps(value, ensure_ascii=False).encode('utf-8'), 'application/json', etag)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, help='固定查看指定目录；省略时自动跟随本工作树最新mission')
    parser.add_argument('--port', type=int, default=8191)
    args = parser.parse_args()
    pinned = args.run.resolve() if args.run else None
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(pinned))
    selection = pinned or '自动跟随最新mission'
    print(f'Stage 5 WebUI: http://127.0.0.1:{args.port}  run={selection}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
