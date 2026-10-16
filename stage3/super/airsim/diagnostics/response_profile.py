"""确定性 NED 平滑加速/制动、两轴往返与八字转向；不依赖 ROS。"""
import json
import math
from pathlib import Path


def segments(c):
    d,t,h=c['line_distance_m'],c['line_duration_s'],c['hold_s']
    return [('north-out','line',t,[0,0,0],[d,0,0]),('north-hold','hold',h,[d,0,0],[0,0,0]),
            ('north-back','line',t,[d,0,0],[-d,0,0]),('center-hold','hold',h,[0,0,0],[0,0,0]),
            ('east-out','line',t,[0,0,0],[0,d,0]),('east-hold','hold',h,[0,d,0],[0,0,0]),
            ('east-back','line',t,[0,d,0],[0,-d,0]),('center-hold','hold',h,[0,0,0],[0,0,0]),
            ('figure8','figure8',c['figure8_duration_s'],[0,0,0],[0,0,0]),
            ('final-hold','hold',3.,[0,0,0],[0,0,0])]


def sample(c,t):
    for name,kind,duration,origin,delta in segments(c):
        if t<=duration:
            u=max(0.,t)/duration
            if kind=='line':
                s=10*u**3-15*u**4+6*u**5
                v=(30*u**2-60*u**3+30*u**4)/duration
                a=(60*u-180*u**2+120*u**3)/duration**2
                return name,[origin[i]+delta[i]*s for i in range(3)],[x*v for x in delta],[x*a for x in delta],False
            if kind=='hold':return name,origin[:],[0.,0.,0.],[0.,0.,0.],False
            w=2*math.pi/duration;angle=w*max(0.,t)
            f=(1-math.cos(angle))/2;df=w*math.sin(angle)/2;ddf=w*w*math.cos(angle)/2
            p=[];v=[];a=[]
            for k,amplitude in [(1,c['figure8_amplitude_m']),(2,c['figure8_amplitude_m']/2)]:
                sn,cs=math.sin(k*angle),math.cos(k*angle)
                p.append(amplitude*sn*f)
                v.append(amplitude*(k*w*cs*f+sn*df))
                a.append(amplitude*(-(k*w)**2*sn*f+2*k*w*cs*df+sn*ddf))
            return name,p+[0.],v+[0.],a+[0.],False
        t-=duration
    return 'complete',[0.,0.,0.],[0.,0.,0.],[0.,0.,0.],True


def load(path):
    c=json.loads(Path(path).read_text())
    for key,value in c.items():
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<=0:
            raise ValueError(key+' 必须为有限正数')
    if c['line_distance_m']>1.5 or c['figure8_amplitude_m']>1.5 or not 1<=c['takeoff_height_m']<=3:
        raise ValueError('首次响应诊断限 1.5 m 幅度、1～3 m 高度')
    duration=sum(s[2] for s in segments(c))
    if duration>120 or c['mission_timeout_wall_s']>600 or c['tracking_error_limit_m']>1:
        raise ValueError('响应诊断时长/误差保护超范围')
    for i in range(2001):
        _,p,v,a,_=sample(c,duration*i/2000)
        if math.hypot(*p[:2])>c['horizontal_envelope_m']-1 or math.dist(v,[0,0,0])>c['max_reference_speed_m_s'] or math.dist(a,[0,0,0])>c['max_reference_acceleration_m_s2']:
            raise ValueError('固定轨迹超过位置、速度或加速度约束')
    return c
