from pymavlink import mavutil
import time,json,argparse
parser=argparse.ArgumentParser(description="PC：比较 PX4 旧/新能力查询响应，不发飞行指令")
parser.add_argument("--output",default="/tmp/airsim-protocol-probe.json")
args=parser.parse_args()
results=[]
c=mavutil.mavlink_connection('udpin:127.0.0.1:14030',source_system=245,source_component=191)
h=c.wait_heartbeat(timeout=8)
if not h:raise RuntimeError('No heartbeat on diagnostic payload link')
print('HEARTBEAT',h.to_dict(),flush=True)
for command,p1 in [(520,1),(512,148)]:
    c.mav.command_long_send(h.get_srcSystem(),h.get_srcComponent(),command,0,p1,0,0,0,0,0,0)
    end=time.monotonic()+4;messages=[]
    while time.monotonic()<end:
        m=c.recv_match(type=['COMMAND_ACK','AUTOPILOT_VERSION'],blocking=True,timeout=.4)
        if m:messages.append(m.to_dict())
    row={'command':command,'messages':messages}
    results.append(row)
    print('PROBE',command,json.dumps(messages),flush=True)

c.close()
json.dump(results,open(args.output,"w"),indent=2)
