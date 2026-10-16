"""终端仪表盘：只显示 PX4/ROS 遥测，不修改控制；无第三方终端依赖。"""
from collections import deque
import math
import sys
import time
import unicodedata


def clean(text, width=88):
    out='';used=0
    for char in str(text):
        if unicodedata.category(char).startswith('C'):continue
        size=2 if unicodedata.east_asian_width(char) in ('W','F') else 1
        if used+size>width:break
        out+=char;used+=size
    return out


def number(value, digits=2):
    return f'{value:.{digits}f}' if value is not None and math.isfinite(value) else '--'


class Dashboard:
    def __init__(self, mode='plain', width=88, stream=None, previous=None):
        self.mode=mode;self.width=max(40,width);self.stream=stream or sys.stdout
        self.previous=previous;self.refs=deque();self.clocks=deque()
        self.peak=None;self.integral=0.;self.duration=0.;self.last=None;self.samples=0
        self.started=time.monotonic();self.last_render=-math.inf;self.active=False;self.last_lines=[]

    def reference(self,stamp,p):
        if not all(math.isfinite(x) for x in [stamp,*p]):return
        if self.refs and stamp<self.refs[-1][0]:self.refs.clear()
        if self.refs and stamp==self.refs[-1][0]:self.refs.pop()
        self.refs.append((stamp,p))
        while self.refs and stamp-self.refs[0][0]>3:self.refs.popleft()

    def clock(self,stamp,wall):
        if self.clocks and stamp<self.clocks[-1][0]:self.clocks.clear()
        if not self.clocks or stamp!=self.clocks[-1][0]:self.clocks.append((stamp,wall))
        while self.clocks and wall-self.clocks[0][1]>5:self.clocks.popleft()

    def odometry(self,stamp,p,v,tracking):
        if not all(math.isfinite(x) for x in [stamp,*p,*v]):return
        if not tracking:self.last=None;return
        if self.last and stamp<=self.last[0]:
            if stamp<self.last[0]:self.last=None
            return
        speed=math.hypot(*v);self.peak=max(self.peak or 0.,speed);self.samples+=1
        if self.last:
            dt=stamp-self.last[0]
            if 0<dt<=.5:self.integral+=(speed+self.last[1])*.5*dt;self.duration+=dt
        self.last=(stamp,speed)

    def metrics(self):
        return dict(tracking_peak_speed_m_s=self.peak,tracking_mean_speed_m_s=self.integral/self.duration if self.duration else None,
                    tracking_sim_seconds=self.duration,tracking_unique_odom_samples=self.samples,
                    meaning='PX4估计的ENU速度，m/s按仿真秒；均值按测量时间加权，仅统计本窗口track阶段，跳过失流')

    def aligned_error(self,stamp,p):
        for (a,x),(b,y) in zip(self.refs,list(self.refs)[1:]):
            if a<=stamp<=b and 0<b-a<=.1:
                ratio=(stamp-a)/(b-a)
                return math.dist(p,[u+(v-u)*ratio for u,v in zip(x,y)])
        return None

    def lines(self,snapshot,wall):
        ages=snapshot.get('ages',{})
        odom=snapshot.get('odom');ref=snapshot.get('reference')
        fresh=odom is not None and ages.get('odom',math.inf)<.5
        ref_fresh=ref is not None and ages.get('sent',math.inf)<.5
        v=odom['v'] if fresh else None;p=odom['p'] if fresh else None
        speed=math.hypot(*v) if v else None
        rtf=None
        if len(self.clocks)>1 and wall-self.clocks[-1][1]<.5:
            a,b=self.clocks[0],self.clocks[-1]
            if b[1]-a[1]>.2:rtf=(b[0]-a[0])/(b[1]-a[1])
        error=self.aligned_error(odom['stamp'],p) if fresh and ref_fresh else None
        state=self.metrics()
        result=[f'AirSim / PX4 / SUPER | 只读遥测 | {wall-self.started:.1f}s',
                f'实际速度 {number(speed)} m/s   水平 {number(math.hypot(*v[:2]) if v else None)}   垂直↑ {number(v[2] if v else None)}',
                f'下发参考 {number(math.hypot(*ref["v"]) if ref_fresh else None)} m/s   配置速度 {number(snapshot.get("configured_speed"))} m/s',
                f'本窗口航段峰值 {number(self.peak)} m/s   均速 {number(state["tracking_mean_speed_m_s"])} m/s',
                '位置 ENU '+(' / '.join(number(x) for x in p) if p else '--')+f' m   同刻误差 {number(error,3)} m',
                f'仿真/墙钟 {number(rtf)}   数据新鲜度 odom {number(ages.get("odom",math.inf)*1000,0)} ms / ref {number(ages.get("sent",math.inf)*1000,0)} ms',
                'PX4 '+snapshot.get('vehicle','--')+(' [状态失流]' if ages.get('vehicle',math.inf)>1.5 else ''),
                '控制 '+snapshot.get('control','等待数据')+(' [失流]' if ages.get('control',math.inf)>1.5 else ''),
                '任务 '+snapshot.get('task','等待数据')+(' [失流]' if ages.get('task',math.inf)>1.5 else '')]
        if not fresh:result.append('注意：里程计缺失/失流，当前速度不显示为 0。')
        if self.previous:
            result.append('上轮报告 '+('成功' if self.previous.get('success') else '失败')+
                          f' | 峰值 {number(self.previous.get("max_speed_m_s"))} m/s | 航段均速 {number(self.previous.get("tracking_mean_speed_m_s"))} m/s')
            result.append('上轮原因 '+self.previous.get('reason',''))
        result.append('速度为 PX4 估计，m/s 按仿真秒；航点进度不代表任务成功。')
        result.append('Ctrl+C：task 请求降落；独立 dashboard 只退出观察。')
        return [clean(line,self.width) for line in result]

    def write(self,text):
        try:self.stream.write(text);self.stream.flush()
        except (OSError,ValueError):self.mode='off'

    def render(self,snapshot,wall=None,force=False):
        wall=time.monotonic() if wall is None else wall
        if self.mode=='off' or (not force and wall-self.last_render<(.25 if self.mode=='ansi' else 1.)):return
        self.last_render=wall;self.last_lines=self.lines(snapshot,wall)
        if self.mode=='ansi':
            if not self.active:self.write('\x1b[?1049h\x1b[?25l');self.active=True
            self.write('\x1b[H'+'\n'.join(self.last_lines)+'\x1b[J')
        else:self.write(' | '.join(self.last_lines[1:5])+' | '+clean(snapshot.get('task','等待数据'),100)+'\n')

    def close(self):
        if self.active:self.write('\x1b[?25h\x1b[?1049l');self.active=False
        if self.mode!='off' and self.last_lines:self.write('\n最终遥测快照（窗口统计）\n'+'\n'.join(self.last_lines)+'\n')


def previous_summary(report):
    """旧报告没有窗口统计时，从已保存测量按同一时间加权口径补齐均速。"""
    summary=dict(report.get('summary',{}));metrics=summary.get('dashboard_window')
    if metrics is None:
        window=Dashboard('off')
        for row in report.get('records',[]):
            window.odometry(row['sim_s'],row['p'],row['v'],row.get('control','').startswith('track:'))
        metrics=window.metrics()
    summary['tracking_mean_speed_m_s']=metrics.get('tracking_mean_speed_m_s')
    return summary
