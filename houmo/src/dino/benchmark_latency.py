"""Sequential HTTP latency benchmark; standard library only, excludes disk saving."""
import argparse
import base64
from collections import Counter
import json
from pathlib import Path
import statistics
import time
import urllib.request


def percentile(values, p):
    values = sorted(values)
    position = (len(values)-1)*p/100
    lo = int(position)
    hi = min(lo+1, len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(position-lo)


def summarize(rows):
    fields = set.intersection(*(set(row['metrics_ms']) for row in rows))
    return {name: {'mean':statistics.mean(values), 'p50':percentile(values,50),
                   'p90':percentile(values,90), 'p95':percentile(values,95),
                   'min':min(values), 'max':max(values),
                   'stdev':statistics.stdev(values) if len(values)>1 else 0.}
            for name in sorted(fields)
            for values in [[row['metrics_ms'][name] for row in rows]]}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--url', default='http://127.0.0.1:8083')
    cli.add_argument('--case', action='append', required=True, help='NAME|IMAGE_PATH|PROMPT')
    cli.add_argument('--transport', required=True, help='Label only, e.g. usb-hdc or board-loopback')
    cli.add_argument('--overlay', choices=('off',), default='off')
    cli.add_argument('--warmup', type=int, default=3)
    cli.add_argument('--repeat', type=int, default=30)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    if args.repeat < 1 or args.warmup < 0:
        cli.error('repeat >= 1 and warmup >= 0 required')
    # Ignore proxy settings for explicitly selected local/USB endpoints.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def health():
        with opener.open(args.url.rstrip('/')+'/health',timeout=10) as response:
            return json.load(response)
    report = {'transport':args.transport,'url':args.url,'warmup':args.warmup,'repeat':args.repeat,
              'before':health(),'scenarios':[],
              'definition':'client_total_ms: base64+request JSON+HTTP upload+full response download+response JSON/base64 decode; excludes source file read and result disk saving. http_roundtrip_ms: prebuilt body to full response received; includes fresh HTTP connection. Serial concurrency=1, no input cache, resident model.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for spec in args.case:
        name, filename, prompt = spec.split('|',2)
        raw = Path(filename).read_bytes()
        for overlay in [False]:
            rows, warmups = [], []
            scenario={'name':name,'image':filename,'image_bytes':len(raw),'prompt':prompt,
                      'overlay':overlay,'rows':rows,'warmups':warmups}
            for index in range(args.warmup+args.repeat):
                overall = time.perf_counter()
                started = time.perf_counter()
                encoded = base64.b64encode(raw).decode('ascii')
                encode_ms = (time.perf_counter()-started)*1000
                started = time.perf_counter()
                body = json.dumps({'image_base64':encoded,'prompt':prompt,'threshold':.35,'overlay':overlay,'profile':True},allow_nan=False).encode()
                json_ms = (time.perf_counter()-started)*1000
                request = urllib.request.Request(args.url.rstrip('/')+'/detect',data=body,headers={'Content-Type':'application/json'})
                started = time.perf_counter()
                with opener.open(request,timeout=300) as response:
                    headers_ms = (time.perf_counter()-started)*1000
                    response_body = response.read()
                    received_ms = (time.perf_counter()-started)*1000
                    timing_header = response.headers.get('Server-Timing','')
                started = time.perf_counter()
                result = json.loads(response_body)
                parse_ms = (time.perf_counter()-started)*1000
                started = time.perf_counter()
                if overlay:
                    base64.b64decode(result['overlay_png_base64'],validate=True)
                decode_ms = (time.perf_counter()-started)*1000
                total_ms = (time.perf_counter()-overall)*1000
                metrics = dict(result['timings_ms'])
                for field in timing_header.split(','):
                    label,_,duration = field.strip().partition(';dur=')
                    if duration: metrics[label]=float(duration)
                metrics.update(client_input_base64_ms=encode_ms,client_request_json_ms=json_ms,
                    http_to_headers_ms=headers_ms,http_response_read_ms=received_ms-headers_ms,
                    http_roundtrip_ms=received_ms,client_response_json_ms=parse_ms,
                    client_overlay_base64_decode_ms=decode_ms,client_total_ms=total_ms,
                    legacy_elapsed_ms=result['elapsed_ms'])
                metrics['http_outside_server_to_headers_ms']=received_ms-metrics['server_to_headers_ms']
                row={'profile_id':result['profile_id'],'metrics_ms':metrics,'request_bytes':len(body),
                     'response_bytes':len(response_body),'detections':len(result['detections']),
                     'labels':dict(Counter(d['label'] for d in result['detections'])),
                     'width':result['width'],'height':result['height']}
                (warmups if index<args.warmup else rows).append(row)
                if index>=args.warmup and (index==args.warmup or (index-args.warmup+1)%10==0):
                    print(name,'overlay='+str(overlay),'sample',index-args.warmup+1,
                          'client_ms',round(total_ms,2),'server_ms',round(metrics['server_to_headers_ms'],2),flush=True)
            scenario['summary_ms']=summarize(rows)
            report['scenarios'].append(scenario)
            report['after']=health()
            if report['after']['worker_pid']!=report['before']['worker_pid']:
                raise RuntimeError('Worker changed during benchmark')
            args.output.write_text(json.dumps(report,indent=2))
            print('DONE',name,'overlay='+str(overlay),json.dumps(scenario['summary_ms']['client_total_ms']),flush=True)
    print('REPORT',args.output,flush=True)


if __name__=='__main__':
    main()
