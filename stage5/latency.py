"""同机单调墙钟延迟日志；不将仿真时间或控制指令提交当作物理响应。"""
import argparse
import json
import math
from pathlib import Path
import statistics
import threading
import time

_LOCK = threading.Lock()


def record(output, component, seconds, **fields):
    if output is None:
        return
    value = dict(component=component, seconds=float(seconds), monotonic_s=time.monotonic(), **fields)
    if not math.isfinite(value['seconds']) or value['seconds'] < 0:
        return
    try:
        with _LOCK, (Path(output)/'latency.jsonl').open('a') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+'\n')
    except OSError:
        pass  # 诊断写入失败不改变控制行为。


def summarize(directory):
    directory = Path(directory)
    path = directory/'latency.jsonl'
    samples = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    historical = not path.exists()
    if historical:
        for path in directory.glob('qwen-*-metrics.json'):
            row = json.loads(path.read_text())
            if 'http_elapsed_s' in row:
                samples.append(dict(component='qwen_http', seconds=row['http_elapsed_s']))
        seen = set()
        for path in directory.glob('attempt-*/flight.json'):
            for row in json.loads(path.read_text()):
                judgment = row.get('judgment', {})
                seconds = judgment.get('latency_s')
                key = (str(path), seconds)
                if judgment.get('source') == 'jev' and seconds is not None and key not in seen:
                    seen.add(key); samples.append(dict(component='jev_request_observed', seconds=seconds))
        path = directory/'bootstrap.jsonl'
        events = {row['event']: row['wall_s'] for row in map(json.loads, path.read_text().splitlines())} if path.exists() else {}
        for component, start, end in [('takeoff_to_hover', 'takeoff_dispatched', 'takeoff_complete'),
                                      ('convoy_start_rpc', 'convoy_start_requested', 'convoy_started')]:
            if start in events and end in events:
                samples.append(dict(component=component, seconds=events[end]-events[start]))
    groups = {}
    for row in samples:
        if isinstance(row.get('seconds'), (int, float)) and math.isfinite(row['seconds']) and row['seconds'] >= 0:
            groups.setdefault(row['component'], []).append(row['seconds']*1000)
    return dict(unit='ms', clock='same-host monotonic wall clock', historical_reconstruction=historical,
                note=('历史Jev仅包含flight.json里可见的去重调用，可能漏掉未采样的调用；未记录的环节不推算。' if historical else
                      'capture_to_command为接收图像到提交控制设定值，不含相机曝光/网络之前延迟或机体响应。'),
                components={name: dict(count=len(values), min=round(min(values), 3), median=round(statistics.median(values), 3),
                    p95=round(sorted(values)[math.ceil(.95*len(values))-1], 3), max=round(max(values), 3))
                    for name, values in sorted(groups.items())})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task_dir', type=Path)
    args = parser.parse_args()
    result = summarize(args.task_dir)
    from stage5.evidence import write_json
    write_json(args.task_dir/'latency-summary.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
