from rpc_client import rpc
import time,json,math,concurrent.futures,argparse,subprocess,re
parser=argparse.ArgumentParser(description="PC：AirSim/PX4 低速仿真飞行检查；不适用于实机")
parser.add_argument("--run",action="store_true",help="执行解锁和飞行")
parser.add_argument("--output",default="/tmp/airsim-flight-check.json")
args=parser.parse_args()
if not args.run: parser.error("飞行检查必须显式传入 --run")
out=args.output
records=[]
original_parameters={}
owns_control=False
landed_ok=False
V='PX4'
def state():
    s=rpc('getMultirotorState',V,timeout=4)
    k=s['kinematics_estimated'];p=k['position'];v=k['linear_velocity']
    q=k['orientation'];yaw=math.degrees(math.atan2(2*(q['w_val']*q['z_val']+q['x_val']*q['y_val']),1-2*(q['y_val']**2+q['z_val']**2)))
    return {'yaw_deg':yaw,'timestamp':s['timestamp'],'p':[p[a+'_val'] for a in 'xyz'],'v':[v[a+'_val'] for a in 'xyz'],'landed':s['landed_state']}
def sample(label):
    s=state();records.append({'label':label,'wall':time.time(),**s});print(label,json.dumps(s),flush=True);return s
pool=concurrent.futures.ThreadPoolExecutor(2)
def action(name,args,limit=35):
    print('COMMAND',name,args,flush=True)
    if name.startswith(('move','rotate')): rpc('enableApiControl',True,V)
    f=pool.submit(rpc,name,*args,timeout=limit+5)
    deadline=time.monotonic()+limit
    last_timestamp=None
    fresh_at=time.monotonic()
    while not f.done():
        s=sample(name)
        if s['timestamp']!=last_timestamp:
            last_timestamp=s['timestamp'];fresh_at=time.monotonic()
        if time.monotonic()-fresh_at>3:
            rpc('cancelLastTask',V);raise RuntimeError('State timestamp stopped updating')
        if not all(math.isfinite(x) for x in s['p']+s['v']):
            rpc('cancelLastTask',V);raise RuntimeError('Non-finite flight state')
        if name!='land' and (abs(s['p'][0])>5 or abs(s['p'][1])>5 or s['p'][2]<-6):
            rpc('cancelLastTask',V);raise RuntimeError('Exceeded flight envelope')
        if time.monotonic()>deadline:
            rpc('cancelLastTask',V);raise TimeoutError(name)
        time.sleep(.7)
    result=f.result();print('RESULT',name,result,flush=True)
    if result is False: raise RuntimeError(name+' returned false')
    return sample(name+'-end')
def hover(label,seconds=4):
    action('hover',[V],10)
    for _ in range(seconds):sample(label);time.sleep(1)
err=None
try:
    initial=sample('initial')
    if initial['landed']!=0: raise RuntimeError('Expected landed vehicle before test')
    if abs(initial['p'][0])>1 or abs(initial['p'][1])>1: raise RuntimeError('Expected vehicle near initial origin')
    subprocess.run(['docker','exec','uav-airsim-px4','/opt/px4-gazebo/bin/px4-commander','mode','auto:loiter'],check=True)
    check=subprocess.run(['docker','exec','uav-airsim-px4','/opt/px4-gazebo/bin/px4-commander','check'],capture_output=True,text=True,check=True)
    if 'Preflight check: OK' not in check.stdout:raise RuntimeError(check.stdout+check.stderr)
    for name in ['MPC_XY_VEL_MAX','MPC_XY_CRUISE','MPC_VEL_MANUAL']:
        raw=subprocess.check_output(['docker','exec','uav-airsim-px4','/opt/px4-gazebo/bin/px4-param','show',name],text=True)
        original_parameters[name]=float(re.search(r':\s*([-0-9.]+)',raw)[1])
    rpc('enableApiControl',True,V)
    owns_control=True
    if not rpc('isApiControlEnabled',V):raise RuntimeError('API control unavailable')
    if not rpc('armDisarm',True,V):raise RuntimeError('Arm rejected')
    take=action('takeoff',[25,V],30)
    if take['p'][2]>-1:raise RuntimeError('Takeoff height too low')
    hover('takeoff-hover')
    z=state()['p'][2]
    action('moveToPosition',[1.,0.,z,.5,20.,0,{'is_rate':True,'yaw_or_rate':0.},-1.,1.,V],25)
    hover('position-hover')
    action('moveByVelocity',[-.25,0.,0.,3.,0,{'is_rate':True,'yaw_or_rate':0.},V],10)
    hover('velocity-hover')
    action('rotateByYawRate',[10.,2.,V],10)
    hover('yaw-hover')
    action('moveToPosition',[0.,0.,z,.5,20.,0,{'is_rate':True,'yaw_or_rate':0.},-1.,1.,V],25)
    hover('return-hover',2)
except Exception as e:
    err=repr(e);print('FAIL',err,flush=True)
finally:
    try:
        if owns_control:
            if err:rpc('cancelLastTask',V)
            action('land',[45,V],50)
            for _ in range(5):
                s=sample('land-settle')
                if s['landed']==0:break
                time.sleep(1)
            if s['landed']!=0:raise RuntimeError('Not landed')
            landed_ok=True
            if not rpc('armDisarm',False,V):raise RuntimeError('Disarm rejected')
            rpc('enableApiControl',False,V)
    except Exception as e:
        print('LAND FAIL',repr(e),flush=True);err=(err or '')+' landing:'+repr(e)
    try:
        for name,value in original_parameters.items():
            subprocess.run(['docker','exec','uav-airsim-px4','/opt/px4-gazebo/bin/px4-param','set',name,str(value)],check=True)
        if landed_ok:
            subprocess.run(['docker','exec','uav-airsim-px4','/opt/px4-gazebo/bin/px4-commander','mode','auto:loiter'],check=True)
    except Exception as e:
        err=(err or '')+' cleanup:'+repr(e)
    json.dump({'error':err,'original_parameters':original_parameters,'records':records},open(out,'w'),indent=2)
    print('REPORT',out,'error=',err,flush=True)
    pool.shutdown(wait=False)
if err:raise SystemExit(1)
