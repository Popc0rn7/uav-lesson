#!/usr/bin/env python3
"""PC：每轮飞行复盘；只读报告/ULog，输出独立 review.json/txt/png。"""
import argparse
from bisect import bisect_left
import json
import math
import os
from pathlib import Path
import statistics
import io

TOPICS = ['trajectory_setpoint', 'vehicle_local_position', 'vehicle_local_position_setpoint',
          'vehicle_attitude', 'vehicle_attitude_setpoint', 'vehicle_angular_velocity',
          'vehicle_rates_setpoint', 'actuator_motors', 'control_allocator_status',
          'estimator_status', 'vehicle_status']


class LogSnapshot(io.BufferedReader):
    """仅解析调用时已存在的前缀，防止追着仍在增长的 ULog 读取。"""
    def __init__(self,path):
        super().__init__(io.FileIO(path,'r'))
        self.limit = os.fstat(self.fileno()).st_size

    def read(self,size=-1):
        remaining = max(0,self.limit-self.tell())
        return super().read(remaining if size<0 else min(size,remaining))


def stats(values):
    values = sorted(float(x) for x in values if math.isfinite(float(x)))
    if not values:
        return None
    return dict(samples=len(values), mean=statistics.fmean(values),
                rms=math.sqrt(statistics.fmean(x*x for x in values)),
                p95=values[round((len(values)-1)*.95)], maximum=values[-1])


def intervals(records, end):
    result = []
    for index, row in enumerate(records):
        if not row.get('control', '').startswith('track:'):
            continue
        start = row['sim_s']
        stop = min(end, records[index+1]['sim_s'] if index+1 < len(records) else start)
        if stop <= start or stop-start > .5:
            continue
        if result and abs(result[-1][1]-start) < 1e-6:
            result[-1][1] = stop
        else:
            result.append([start, stop])
    return result


def interpolate_rows(rows, stamp, max_gap=.1, times=None):
    """按测量时间插值，禁止外推/跨越失流；适用于 ENU 位置/速度参考。"""
    times = times if times is not None else [r['sim_s'] for r in rows]
    i = bisect_left(times, stamp)
    if i < len(rows) and abs(times[i]-stamp) < 1e-7:
        return rows[i]['p']
    if i == 0 or i == len(rows) or times[i]-times[i-1] > max_gap:
        return None
    ratio = (stamp-times[i-1])/(times[i]-times[i-1])
    return [a+(b-a)*ratio for a,b in zip(rows[i-1]['p'], rows[i]['p'])]


def core_review(report):
    rows = report.get('records', [])
    collisions = [c['data']['time_stamp']*1e-9 for c in report['summary'].get('contacts', [])
                  if report['summary'].get('collision', False)]
    end = min(collisions, default=rows[-1]['sim_s'] if rows else 0)
    spans = intervals(rows, end)
    def same_span(a,b):
        return any(start<=a<=b<=stop for start,stop in spans)
    tracked = [r for r in rows if r.get('control','').startswith('track:') and r['sim_s'] <= end]
    unique = {r['sim_s']:r for r in tracked}
    tracked = sorted(unique.values(), key=lambda r:r['sim_s'])
    result = dict(schema_version=1, flight_result=report['summary'], tracking_intervals_s=spans,
                  collision_sim_s=collisions, legacy_error_warning='旧 tracking_error_m 为最近收到的规划参考与测量位置之差；不是严格同一采样时刻的飞控误差。',
                  telemetry=dict(unique_tracking_samples=len(tracked),
                                 odom_age_s=stats(r.get('odom_age_s',math.nan) for r in tracked),
                                 odom_sample_gap_s=stats(b['sim_s']-a['sim_s'] for a,b in zip(tracked,tracked[1:]) if same_span(a['sim_s'],b['sim_s'])),
                                 observed_speed_m_s=stats(math.dist(r['v'],[0,0,0]) for r in tracked)),
                  limitations=[], findings=[])
    sent = sorted({r['sim_s']:r for r in report.get('references', []) if r.get('kind')=='sent'}.values(),key=lambda r:r['sim_s'])
    errors = []
    times = [r['sim_s'] for r in sent]
    for row in tracked:
        p = interpolate_rows(sent,row['sim_s'],times=times)
        if p is not None:
            errors.append(math.dist(p,row['p']))
    result['telemetry']['aligned_sent_position_error_m'] = stats(errors)
    result['telemetry']['reference_sample_gap_s'] = stats(b['sim_s']-a['sim_s'] for a,b in zip(sent,sent[1:]) if same_span(a['sim_s'],b['sim_s']))
    for kind in ('cmd','sent'):
        samples = [r for r in report.get('references',[]) if r.get('kind')==kind and
                   any(a<=r['sim_s']<=b for a,b in spans)]
        result['telemetry'][kind+'_receive_age_sim_s'] = stats(r['received_sim_s']-r['sim_s'] for r in samples if r.get('received_sim_s') is not None)
        result['telemetry'][kind+'_wall_gap_s'] = stats(b['received_wall_s']-a['received_wall_s'] for a,b in zip(samples,samples[1:])
                                                      if 'received_wall_s' in a and 'received_wall_s' in b and same_span(a['sim_s'],b['sim_s']))
    if any(b['sim_s']<a['sim_s'] for a,b in zip(rows,rows[1:])):
        result['limitations'].append('记录包含仿真时间回跳；跨复位的时间窗口可能重叠，不能将整轮当作单一连续轨迹。')
    if not errors:
        result['limitations'].append('该历史报告未保存独立的实际下发参考时间序列，ROS 报告不能严格分离规划与飞控跟踪。')
    if collisions:
        result['findings'].append('已记录空中碰撞；内环与轨迹指标仅统计碰撞前 tracking 阶段，避免把撞后翻滚/降落混作控制能力。')
    result['findings'].append('SimpleFlight 与 PX4 当前控制律、定位反馈和轨迹执行方式不同；机体参数是否变化需另行核实，历史不同速度/路线不能直接归因为飞控性能差异。')
    return result


def analyse_ulog(path, spans):
    import numpy as np
    from pyulog import ULog
    stream = LogSnapshot(path)
    size = stream.limit
    try:
        log = ULog(stream, message_name_filter_list=TOPICS)
    finally:
        stream.close()
    tables = {d.name:d.data for d in log.data_list if d.multi_id == 0}
    series = {}
    metrics = dict(path=str(path), snapshot_bytes=size, available_topics=sorted(tables), missing_topics=sorted(set(TOPICS)-set(tables)),
                   file_corrupt=bool(log.file_corruption), dropouts=[], parameters={}, parameter_changes=[])
    def mask(t):
        out = np.zeros(len(t),dtype=bool)
        for a,b in spans:
            out |= (t>=a)&(t<=b)
        return out
    def table(name, fields, sample=False):
        data = tables.get(name)
        if data is None or not all(k in data for k in fields):
            return np.empty(0), np.empty((0,len(fields)))
        key = 'timestamp_sample' if sample and 'timestamp_sample' in data else 'timestamp'
        t = np.asarray(data[key],dtype=float)*1e-6
        y = np.column_stack([data[k] for k in fields]).astype(float)
        keep = mask(t)&np.isfinite(y).all(axis=1)
        t,y = t[keep],y[keep]
        _,i = np.unique(t,return_index=True)
        return t[i],y[i]
    def align(t, source_t, source, max_gap=.3):
        if len(source_t)<2:
            return np.full((len(t),source.shape[1]),np.nan)
        index = np.clip(np.searchsorted(source_t,t,side='right'),1,len(source_t)-1)
        good = ((t>=source_t[0])&(t<=source_t[-1])&((source_t[index]-source_t[index-1])<=max_gap))
        for start,end in spans:
            good &= ~((t>=start)&(t<=end)&((source_t[index-1]<start)|(source_t[index]>end)))
        out = np.column_stack([np.interp(t,source_t,source[:,k]) for k in range(source.shape[1])])
        out[~good] = np.nan
        return out
    def pair(label, actual_name, actual_fields, target_name, target_fields, sample=True):
        t,actual = table(actual_name,actual_fields,sample)
        rt,target = table(target_name,target_fields)
        desired = align(t,rt,target)
        error = np.linalg.norm(actual-desired,axis=1)
        metrics[label] = stats(error)
        series[label] = (t,actual,desired,error)
        metrics[label+'_reference_gap_s'] = stats(np.diff(rt))
        return t,actual,desired,error
    pair('position_error_m','vehicle_local_position',['x','y','z'],'trajectory_setpoint',[f'position[{i}]' for i in range(3)])
    pair('velocity_controller_error_m_s','vehicle_local_position',['vx','vy','vz'],'vehicle_local_position_setpoint',['vx','vy','vz'])
    pair('rate_error_rad_s','vehicle_angular_velocity',[f'xyz[{i}]' for i in range(3)],'vehicle_rates_setpoint',['roll','pitch','yaw'])
    # 描述响应延迟，不把相关性当作因果；低激励时不给出延迟估计。
    t,actual,target,error = series['velocity_controller_error_m_s']
    rt,rv = table('vehicle_local_position_setpoint',['vx','vy','vz'])
    metrics['velocity_best_delay_s'] = None
    if len(t)>20 and len(rt)>2 and float(np.linalg.norm(np.std(rv,axis=0)))>.3:
        trials = []
        for delay in np.linspace(0,.8,81):
            delayed = align(t-delay,rt,rv)
            residual = np.linalg.norm(actual-delayed,axis=1)
            valid = np.isfinite(residual)
            if valid.sum()>=len(t)*.7:
                trials.append((float(np.sqrt(np.mean(residual[valid]**2))),float(delay)))
        if trials:
            best = min(trials)
            metrics['velocity_best_delay_s'] = best[1]
            metrics['velocity_delay_compensated_rms_m_s'] = best[0]
    t,q = table('vehicle_attitude',[f'q[{i}]' for i in range(4)],True)
    rt,qd = table('vehicle_attitude_setpoint',[f'q_d[{i}]' for i in range(4)])
    if len(qd):
        for i in range(1,len(qd)):
            if np.dot(qd[i-1],qd[i])<0:
                qd[i] *= -1
    desired = align(t,rt,qd)
    q /= np.maximum(np.linalg.norm(q,axis=1,keepdims=True),1e-12)
    desired /= np.maximum(np.linalg.norm(desired,axis=1,keepdims=True),1e-12)
    angle = np.degrees(2*np.arccos(np.clip(np.abs(np.sum(q*desired,axis=1)),0,1)))
    metrics['attitude_error_deg'] = stats(angle)
    series['attitude_error_deg'] = (t,angle)
    for label,quat in [('actual_tilt_deg',q),('desired_tilt_deg',desired)]:
        tilt = np.degrees(np.arccos(np.clip(1-2*(quat[:,1]**2+quat[:,2]**2),-1,1)))
        metrics[label] = stats(tilt)
        if label == 'desired_tilt_deg': desired_tilt = tilt
    mt,motors = table('actuator_motors',[f'control[{i}]' for i in range(4)])
    metrics['motor_samples'] = len(mt)
    metrics['any_motor_ge_098_fraction'] = float(np.mean(np.any(motors>=.98,axis=1))) if len(mt) else None
    metrics['any_motor_le_002_fraction'] = float(np.mean(np.any(motors<=.02,axis=1))) if len(mt) else None
    series['motors'] = (mt,motors)
    for field in ('torque_setpoint_achieved','thrust_setpoint_achieved'):
        at,values = table('control_allocator_status',[field])
        metrics[field+'_false_fraction'] = float(np.mean(values[:,0]==0)) if len(at) else None
    for field in ('vel_test_ratio','pos_test_ratio','hgt_test_ratio','hdg_test_ratio'):
        et,values = table('estimator_status',[field],True)
        metrics[field] = stats(values[:,0])
        metrics[field+'_gt1_fraction'] = float(np.mean(values[:,0]>1)) if len(et) else None
    for field in ('xy_reset_counter','z_reset_counter','heading_reset_counter'):
        et,values = table('vehicle_local_position',[field])
        metrics[field+'_changes'] = int(np.count_nonzero(np.diff(values[:,0]))) if len(et) else None
    # p/v/a 相互一致性：不是将所有位置步长都当作异常跳变。
    st,sp = table('trajectory_setpoint',[f'{key}[{i}]' for key in ('position','velocity','acceleration') for i in range(3)])
    dt = np.diff(st)
    good = (dt>0)&(dt<=.3)
    residual = sp[1:,:3]-sp[:-1,:3]-(sp[1:,3:6]+sp[:-1,3:6])*.5*dt[:,None]
    metrics['reference_pv_residual_m'] = stats(np.linalg.norm(residual[good],axis=1))
    metrics['reference_acceleration_m_s2'] = stats(np.linalg.norm(sp[:,6:9],axis=1))
    metrics['reference_jerk_m_s3'] = stats(np.linalg.norm(np.diff(sp[:,6:9],axis=0)[good]/dt[good,None],axis=1))
    for key,value in log.initial_parameters.items():
        if key.startswith(('MPC_','MC_','EKF2_','SENS_GPS','UXRCE_','COM_OF','COM_OBL','SYS_AUTOSTART')):
            metrics['parameters'][key] = value
    if spans:
        for stamp,name,value in log.changed_parameters:
            if stamp*1e-6 <= spans[0][0] and name in metrics['parameters']:
                metrics['parameters'][name] = value
            if spans[0][0] <= stamp*1e-6 <= spans[-1][1]:
                metrics['parameter_changes'].append(dict(sim_s=stamp*1e-6,name=name,value=value))
        for drop in log.dropouts:
            if any(drop.timestamp*1e-6<=b and (drop.timestamp*1e-6+drop.duration*.001)>=a for a,b in spans):
                metrics['dropouts'].append(dict(sim_s=drop.timestamp*1e-6,duration_ms=drop.duration))
    tilt_limit = metrics['parameters'].get('MPC_TILTMAX_AIR')
    finite_tilt = desired_tilt[np.isfinite(desired_tilt)]
    metrics['desired_tilt_near_limit_fraction'] = float(np.mean(finite_tilt>=tilt_limit-.5)) if tilt_limit is not None and len(finite_tilt) else None
    return metrics,series


def plot_review(path,series,spans):
    import numpy as np
    os.environ.setdefault('MPLCONFIGDIR', str(path.parent/'.matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes = plt.subplots(3,2,figsize=(13,10))
    t0 = spans[0][0] if spans else 0
    for label,axis,title in [('position_error_m',axes[0,1],'Position tracking error (m)'),
                             ('velocity_controller_error_m_s',axes[1,0],'Velocity: actual / controller target (m/s)'),
                             ('rate_error_rad_s',axes[1,1],'Body rate tracking error (rad/s)')]:
        t,actual,target,error = series[label]
        if label == 'velocity_controller_error_m_s':
            axis.plot(t-t0,np.linalg.norm(actual,axis=1),label='actual')
            axis.plot(t-t0,np.linalg.norm(target,axis=1),label='controller target')
            axis.legend()
        else:
            axis.plot(t-t0,error)
        axis.set_title(title)
    t,actual,target,error = series['position_error_m']
    axes[0,0].plot(actual[:,1],actual[:,0],label='PX4 estimate')
    axes[0,0].plot(target[:,1],target[:,0],label='external setpoint',alpha=.7)
    axes[0,0].set(xlabel='East (m)',ylabel='North (m)',title='NED horizontal trajectory')
    axes[0,0].axis('equal');axes[0,0].legend()
    t,angle = series['attitude_error_deg']
    axes[2,0].plot(t-t0,angle);axes[2,0].set_title('Attitude tracking error (deg)')
    t,motors = series['motors']
    axes[2,1].plot(t-t0,motors);axes[2,1].set_title('Motor commands (0..1; bound != proof of saturation)')
    for ax in axes.flat:
        ax.grid(alpha=.3)
        if ax != axes[0,0]: ax.set_xlabel('Tracking time (simulation s)')
    fig.tight_layout();fig.savefig(path,dpi=150);plt.close(fig)


def review(path, ulog=None):
    report = json.loads(path.read_text())
    result = core_review(report)
    result['source_report'] = str(path.resolve())
    task_file = path.parent/'task.json'
    if task_file.exists(): result['task_snapshot'] = json.loads(task_file.read_text())
    output = path.with_name(path.stem+'.review.json')
    candidates = [Path(ulog)] if ulog else sorted(path.parent.glob('px4-logs/**/*.ulg'))
    result['ulog_attempts'] = []
    if result['tracking_intervals_s']:
        for candidate in candidates:
            try:
                metrics,series = analyse_ulog(candidate,result['tracking_intervals_s'])
                if not metrics.get('position_error_m'):
                    result['ulog_attempts'].append(dict(path=str(candidate),error='没有覆盖本轮 tracking 的有效参考/位置样本'))
                    continue
                result['px4'] = metrics
                try:
                    plot_review(output.with_suffix('.png'),series,result['tracking_intervals_s'])
                except ImportError:
                    result['limitations'].append('未安装 matplotlib，未生成曲线。')
                break
            except ImportError:
                result['limitations'].append('未安装 pyulog/numpy：本轮只生成 ROS 复盘，不能评估姿态/角速度内环和分配器余量。')
                break
            except Exception as exc:
                result['ulog_attempts'].append(dict(path=str(candidate),error=str(exc)))
    if 'px4' not in result:
        result['limitations'].append('ULog 内环证据缺失或不覆盖本次任务；不据此判断 PID/动力学原因。')
    else:
        metrics = result['px4']
        result['findings'].append('已按 PX4 测量时间对齐实际位置/速度/姿态/角速度与参考；ULog 降采样参考使用有界间隔插值，细节低于记录频率时仍不确定。')
        for field in ('torque_setpoint_achieved','thrust_setpoint_achieved'):
            fraction = metrics.get(field+'_false_fraction')
            if fraction is not None and fraction > .01:
                result['findings'].append(f'分配器 {field}=false 占 {fraction:.1%}：检查需求、推力/力矩余量及模型，再决定是否调增益。')
        if metrics.get('attitude_error_deg') and metrics['attitude_error_deg']['p95']>10:
            result['findings'].append(f'碰撞前姿态误差 P95={metrics["attitude_error_deg"]["p95"]:.2f}°，应优先检查姿态/角速度响应、仿真执行延迟与模型匹配；这只是诊断线索，不足以单独归因 PID。')
        if metrics.get('velocity_best_delay_s') is not None:
            result['findings'].append(f'速度响应最佳匹配延迟约 {metrics["velocity_best_delay_s"]:.2f} s（仿真时间，扫描范围 0～0.8 s）；该值不是独立测得的网络延迟。')
        fraction = metrics.get('desired_tilt_near_limit_fraction')
        if fraction is not None and fraction>.01:
            result['findings'].append(f'姿态目标接近 MPC_TILTMAX_AIR 上限的样本占 {fraction:.1%}；需评估外部轨迹需求与控制余量的匹配，不直接提高上限。')
        if metrics['file_corrupt'] or metrics['dropouts']:
            result['limitations'].append('ULog 存在截断/损坏或记录掉包；需要核查当前统计窗口的覆盖情况。')
        gap = metrics.get('position_error_m_reference_gap_s')
        if gap and gap['maximum']>.1:
            result['limitations'].append(f'ULog 外部参考最大记录间隔 {gap["maximum"]:.3f} s；不据此推断真实 Offboard 发送频率，未来使用 ROS 独立发送记录核对。')
        result['findings'].append('下一轮按“参考连续性/时序 → 状态估计 → 速度环 → 姿态/角速度环 → 分配器/机体模型”排查；固定路线、出生点与策略，每轮只改一个因素。')
    output.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
    lines = [f'源报告：{path}',f'飞行结果：{report["summary"].get("success")} / {report["summary"].get("reason")}',
             '统计范围：碰撞前 tracking，排除起飞、悬停、降落和撞后状态。']
    if 'px4' in result:
        for key in ('position_error_m','velocity_controller_error_m_s','attitude_error_deg','rate_error_rad_s',
                    'reference_pv_residual_m','reference_acceleration_m_s2'):
            lines.append(key+'：'+json.dumps(result['px4'].get(key),ensure_ascii=False))
        for key in ('any_motor_ge_098_fraction','torque_setpoint_achieved_false_fraction','thrust_setpoint_achieved_false_fraction'):
            lines.append(f'{key}：{result["px4"].get(key)}')
    lines += result['findings'] + ['证据限制：'+s for s in result['limitations']]
    output.with_suffix('.txt').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines));print('复盘：'+str(output))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--ulog',type=Path,help='指定 ULog；默认在同运行目录自动匹配')
    args = parser.parse_args()
    review(args.report,args.ulog)


if __name__ == '__main__': main()
