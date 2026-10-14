"""PC：只读采样 PX4 传感器；结果写入 /tmp，不执行解锁。"""
import subprocess,concurrent.futures,re,json,time,statistics,argparse,pathlib
parser=argparse.ArgumentParser()
parser.add_argument("--output-dir",default="/tmp/airsim-sensors")
args=parser.parse_args()
output=pathlib.Path(args.output_dir);output.mkdir(parents=True,exist_ok=True)
names=['sensor_accel','sensor_gyro','sensor_baro','sensor_mag','vehicle_gps_position','vehicle_local_position']
def collect(topic):
    t=time.monotonic()
    r=subprocess.run(['docker','exec','uav-airsim-px4','timeout','12','/opt/px4-gazebo/bin/px4-listener',topic,'-n','120'],capture_output=True,text=True)
    raw=r.stdout+r.stderr
    open(output/(topic+'.txt'),'w').write(raw)
    ts=[int(x) for x in re.findall(r'^    timestamp: (\d+)',raw,re.M)]
    dif=[b-a for a,b in zip(ts,ts[1:])]
    out={'topic':topic,'rc':r.returncode,'samples':len(ts),'wall_seconds':round(time.monotonic()-t,3)}
    if dif:out.update(sim_hz=round(1e6/statistics.mean(dif),2),min_dt_us=min(dif),max_dt_us=max(dif),non_increasing=sum(x<=0 for x in dif))
    fields={'sensor_accel':['x','y','z'],'sensor_gyro':['x','y','z'],'sensor_baro':['pressure'],'sensor_mag':['x','y','z']}.get(topic)
    if fields:
        rows=[]
        for block in raw.split('TOPIC:')[1:]:
            values=[re.search(r'^    '+f+r': ([\-0-9.]+)',block,re.M) for f in fields]
            if all(values):rows.append([float(v[1]) for v in values])
        if len(rows)>1:
            out['mean_values']=dict(zip(fields,[statistics.mean(v) for v in zip(*rows)]))
            out['value_changes']=sum(a!=b for a,b in zip(rows,rows[1:]))
    print(json.dumps(out),flush=True);return out
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as p:
    result=list(p.map(collect,names))
json.dump(result,open(output/'summary.json','w'),indent=2)

if any(r["rc"]!=0 or r["samples"]<120 or r.get("non_increasing",1)>0 for r in result):raise SystemExit(1)
