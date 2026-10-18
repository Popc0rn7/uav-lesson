"""Offline task/ULog review; does not change flight parameters."""
import json
import math
from pathlib import Path

from stage4.contracts import atomic_json


def percentile(values, fraction):
    return sorted(values)[min(len(values)-1,round((len(values)-1)*fraction))] if values else None


def tracking(log, records):
    """Compare logged PX4 references to measurements over the Offboard interval."""
    import numpy as np
    if not records: return {}
    start,end=records[0]['sim_s']*1e6,records[-1]['sim_s']*1e6
    topics={item.name:item.data for item in log.data_list if item.multi_id==0}
    results={}
    def error(name,reference,measured,reference_fields,measured_fields,quaternion=False):
        if reference not in topics or measured not in topics: return
        ref,actual=topics[reference],topics[measured]
        if not all(k in ref for k in reference_fields) or not all(k in actual for k in measured_fields): return
        t=actual.get('timestamp_sample',actual['timestamp']); mask=(t>=start)&(t<=end)&(t>=ref['timestamp'][0])&(t<=ref['timestamp'][-1])
        t=t[mask]
        a=np.array([actual[k][mask] for k in measured_fields]).T
        reference_values=np.array([ref[k] for k in reference_fields],dtype=float).T
        if quaternion and len(reference_values)>1:
            # q and -q encode the same attitude. Preserve sign continuity before
            # interpolation rather than creating an artificial half-turn.
            flips=np.where(np.sum(reference_values[1:]*reference_values[:-1],axis=1)<0,-1.,1.)
            reference_values*=np.r_[1.,np.cumprod(flips)][:,None]
        b=np.array([np.interp(t,ref['timestamp'],reference_values[:,i]) for i in range(len(reference_fields))]).T
        valid=np.isfinite(a).all(axis=1)&np.isfinite(b).all(axis=1)
        a,b=a[valid],b[valid]
        if not len(a): return
        if quaternion:
            a=a/np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-12)
            b=b/np.maximum(np.linalg.norm(b,axis=1,keepdims=True),1e-12)
            e=np.degrees(2*np.arccos(np.clip(np.abs((a*b).sum(axis=1)),0,1)))
        else: e=np.linalg.norm(a-b,axis=1)
        results[name]=dict(samples=len(e),p50=float(np.percentile(e,50)),p95=float(np.percentile(e,95)),maximum=float(max(e)))
    error('position_error_m','vehicle_local_position_setpoint','vehicle_local_position',('x','y','z'),('x','y','z'))
    error('velocity_error_m_s','vehicle_local_position_setpoint','vehicle_local_position',('vx','vy','vz'),('vx','vy','vz'))
    error('attitude_error_deg','vehicle_attitude_setpoint','vehicle_attitude',
          tuple(f'q_d[{i}]' for i in range(4)),tuple(f'q[{i}]' for i in range(4)),True)
    error('angular_rate_error_rad_s','vehicle_rates_setpoint','vehicle_angular_velocity',
          ('roll','pitch','yaw'),tuple(f'xyz[{i}]' for i in range(3)))
    if 'actuator_motors' in topics:
        data=topics['actuator_motors']; mask=(data['timestamp']>=start)&(data['timestamp']<=end)
        motors=np.array([data[f'control[{i}]'][mask] for i in range(4)])
        values=motors[np.isfinite(motors)]
        if len(values): results['motor_outputs']=dict(peak=float(max(values)),fraction_ge_098=float(np.mean(values>=.98)))
    return results


def review(directory):
    report_path=directory/'report.json'
    report=json.loads(report_path.read_text()) if report_path.exists() else None
    records=[json.loads(line) for line in (directory/'flight.jsonl').read_text().splitlines()] if (directory/'flight.jsonl').exists() else []
    # Never include post-collision samples in tracking claims.
    collision_path=directory/'collision.json'
    collision=json.loads(collision_path.read_text()) if collision_path.exists() else None
    collision_s=collision.get('time_stamp',0)*1e-9 if collision else None
    records=[r for r in records if collision_s is None or r['sim_s']<collision_s]
    errors=[math.dist(r['position_ned'],r['reference_ned']) for r in records]
    speeds=[math.dist(r['velocity_ned'],[0,0,0]) for r in records]
    inference=[r for r in records if r['mode']=='infer']
    hold_errors=[math.dist(r['position_ned'],r['reference_ned']) for r in inference]
    inference_path=directory/'inference.jsonl'
    calls=[json.loads(line) for line in inference_path.read_text().splitlines()] if inference_path.exists() else []
    cycles=[b['observation_time_s']-a['observation_time_s'] for a,b in zip(calls,calls[1:])]
    http=[c['http_seconds'] for c in calls]; processing=[c['elapsed_seconds'] for c in calls]
    result=dict(report=report,collision=collision,
                evaluation=json.loads((directory/'evaluation.json').read_text()) if (directory/'evaluation.json').exists() else None,
                tracking_samples=len(records),
                position_error_m_p50=percentile(errors,.5),position_error_m_p95=percentile(errors,.95),
                speed_peak_m_s=max(speeds,default=None),inference_hold_error_m_p95=percentile(hold_errors,.95),
                timing=dict(model_calls=len(calls),http_seconds_p50=percentile(http,.5),http_seconds_p95=percentile(http,.95),
                            model_processing_seconds_p50=percentile(processing,.5),
                            observation_cycle_sim_seconds_p50=percentile(cycles,.5),
                            observation_cycle_sim_seconds_p95=percentile(cycles,.95)),ulogs=[])
    from pyulog import ULog
    for path in sorted((directory/'px4-logs').rglob('*.ulg')):
        log=ULog(str(path)); topics={item.name for item in log.data_list}
        parameters=dict(log.initial_parameters)
        for _,name,value in log.changed_parameters: parameters[name]=value
        result['ulogs'].append(dict(path=str(path.relative_to(directory)),duration_s=(log.last_timestamp-log.start_timestamp)*1e-6,
            topics=sorted(topics),parameters_final={k:parameters.get(k) for k in
                ('SENS_GPS0_DELAY','MC_REF_FF','COM_OF_LOSS_T','COM_OBL_RC_ACT','UXRCE_DDS_SYNCT',
                 'MPC_ACC_HOR','MPC_ACC_HOR_MAX','MPC_XY_VEL_MAX','MPC_TILTMAX_AIR',
                 'MPC_Z_VEL_MAX_UP','MPC_Z_VEL_MAX_DN')},
            parameter_changes=[dict(timestamp=t,name=k,value=v) for t,k,v in log.changed_parameters],
            offboard_tracking=tracking(log,records)))
    result['limitations']='ULog references are interpolated at measurement times over the logged Offboard interval, excluding post-collision data. Motor headroom is only an output proxy; not proof of allocator feasibility.'
    atomic_json(directory/'review.json',result)
    return result
