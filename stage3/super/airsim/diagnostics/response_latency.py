"""离线统一响应拟合；均匀采样、固定比较窗口，不把闭环时间平移称作网络延迟。"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_flight import core_review,LogSnapshot


def fit(actual_t,actual,reference_t,reference,spans,*,max_gap=.3,min_excitation=.05):
    def prepare(t,y):
        t=np.asarray(t,dtype=float);y=np.asarray(y,dtype=float)
        if y.ndim!=2 or len(t)!=len(y):raise ValueError('时间和向量形状不匹配')
        good=np.isfinite(t)&np.isfinite(y).all(axis=1);t,y=t[good],y[good]
        order=np.argsort(t,kind='stable');t,y=t[order],y[order]
        _,indices=np.unique(t,return_index=True)
        return t[indices],y[indices]
    at,ay=prepare(actual_t,actual);rt,ry=prepare(reference_t,reference)
    if len(at)<3 or len(rt)<3:return dict(valid=False,reason='insufficient samples')
    # 每个候选 lag 使用相同样本；保留所有窗口边界和数据缺口保护。
    lags=np.arange(-20,81,dtype=float)*.01
    windows=[np.arange(a+.8,b-.2,.02) for a,b in spans if b-a>1.2]
    grid=np.concatenate(windows) if windows else np.array([])
    def interpolate(t,y,q):
        index=np.clip(np.searchsorted(t,q,side='right'),1,len(t)-1)
        good=(q>=t[0])&(q<=t[-1])&(t[index]-t[index-1]<=max_gap)
        same_span=np.zeros(len(q),dtype=bool)
        for a,b in spans:same_span |= (t[index-1]>=a)&(t[index]<=b)
        good &= same_span
        values=np.column_stack([np.interp(q,t,y[:,i]) for i in range(y.shape[1])]);values[~good]=np.nan
        return values
    measured=interpolate(at,ay,grid)
    targets=[interpolate(rt,ry,grid-lag) for lag in lags]
    good=np.isfinite(measured).all(axis=1)
    for target in targets:good &= np.isfinite(target).all(axis=1)
    if good.sum()<50:return dict(valid=False,reason='insufficient common support; gaps are not interpolated across')
    targets=[target[good] for target in targets];measured=measured[good]
    zero=int(np.argmin(abs(lags)));excitation=float(np.linalg.norm(np.std(targets[zero],axis=0)))
    if excitation<min_excitation:return dict(valid=False,reason='insufficient reference excitation',reference_std=excitation)
    rms=np.array([np.sqrt(np.mean(np.sum((measured-target)**2,axis=1))) for target in targets])
    best=int(np.argmin(rms));near=lags[rms<=rms[best]*1.01+1e-9]
    return dict(valid=True,best_shift_sim_s=float(lags[best]),zero_shift_rms=float(rms[zero]),best_shift_rms=float(rms[best]),
                relative_rms_improvement=float(1-rms[best]/rms[zero]) if rms[zero]>0 else 0,
                near_best_1percent_range_sim_s=[float(near[0]),float(near[-1])],
                at_search_boundary=best in (0,len(lags)-1),samples=int(good.sum()),reference_std=excitation,
                scan=[dict(shift_sim_s=float(lag),rms=float(value)) for lag,value in zip(lags,rms)])


def analyse(report_path):
    report=json.loads(report_path.read_text());spans=core_review(report)['tracking_intervals_s']
    rows=[r for r in report['records'] if r.get('control','').startswith('track:')]
    refs=sorted({r['sim_s']:r for r in report['references'] if r['kind']=='sent'}.values(),key=lambda r:r['sim_s'])
    result=dict(scope='闭环最佳时间平移，不是纯时延；不同参考的拟合值不能相减或相加。时间为仿真秒，状态来自 PX4 估计。',report=str(report_path),fits={})
    result['fits']['external_velocity_to_estimated_velocity']=fit([r['sim_s'] for r in rows],[r['v'] for r in rows],
                                                                  [r['sim_s'] for r in refs],[r['v'] for r in refs],spans,max_gap=.1)
    if len(rows)>1:
        ratio=(rows[-1]['sim_s']-rows[0]['sim_s'])/(rows[-1]['wall_s']-rows[0]['wall_s'])
        result['sim_wall_ratio']=ratio
        v=result['fits']['external_velocity_to_estimated_velocity']
        if v.get('valid'):v['approximate_wall_shift_s']=v['best_shift_sim_s']/ratio
    from pyulog import ULog
    # 通过已匹配本轮 tracking 的复盘路径选 ULog，禁止猜最新一份日志。
    review_path=report_path.with_name(report_path.stem+'.review.json')
    review=json.loads(review_path.read_text()) if review_path.exists() else {}
    selected=review.get('px4',{}).get('path')
    if selected:
        with LogSnapshot(Path(selected)) as stream:
            log=ULog(stream,message_name_filter_list=['vehicle_local_position','vehicle_local_position_setpoint','vehicle_attitude','vehicle_attitude_setpoint','vehicle_angular_velocity','vehicle_rates_setpoint'])
        tables={d.name:d.data for d in log.data_list if d.multi_id==0}
        def table(name,fields,sample=False):
            d=tables[name];key='timestamp_sample' if sample and 'timestamp_sample' in d else 'timestamp'
            return np.asarray(d[key],dtype=float)*1e-6,np.column_stack([d[f] for f in fields])
        def pair(label,actual_name,actual_fields,target_name,target_fields,minimum):
            at,ay=table(actual_name,actual_fields,True);rt,ry=table(target_name,target_fields)
            result['fits'][label]=fit(at,ay,rt,ry,spans,min_excitation=minimum)
        pair('internal_velocity_target_to_estimated_velocity','vehicle_local_position',['vx','vy','vz'],
             'vehicle_local_position_setpoint',['vx','vy','vz'],.05)
        pair('body_rate_target_to_gyro','vehicle_angular_velocity',['xyz[0]','xyz[1]','xyz[2]'],
             'vehicle_rates_setpoint',['roll','pitch','yaw'],.005)
        # 小角度低速诊断仅比较四元数导出的 roll/pitch，避开偏航 wrap。
        def tilt(q):
            w,x,y,z=q.T
            return np.column_stack([np.arctan2(2*(w*x+y*z),1-2*(x*x+y*y)),np.arcsin(np.clip(2*(w*y-z*x),-1,1))])
        at,q=table('vehicle_attitude',[f'q[{i}]' for i in range(4)],True)
        rt,qd=table('vehicle_attitude_setpoint',[f'q_d[{i}]' for i in range(4)])
        result['fits']['attitude_target_to_estimated_tilt']=fit(at,tilt(q),rt,tilt(qd),spans,min_excitation=.005)
        result['ulog']=selected
    else:result['ulog_limit']='没有已匹配的 ULog，未计算内环响应'
    path=report_path.with_name(report_path.stem+'.latency.json');path.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
    print(json.dumps({**result,'fits':{k:{a:b for a,b in v.items() if a!='scan'} for k,v in result['fits'].items()}},indent=2,ensure_ascii=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report',type=Path)
    analyse(parser.parse_args().report)
