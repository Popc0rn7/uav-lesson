"""只读合并 ROS 旁路观察、HIL PCAP 与可选 PX4 ULog；明确每项测量边界。"""
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_flight import stats
from hil import decode


def analyse(directory,ulog=None):
    rows=[json.loads(line) for line in (directory/'ros.jsonl').read_text().splitlines() if line.strip()]
    topics=defaultdict(list)
    for row in rows:topics[row['kind']].append(row)
    result=dict(scope='旁路观察不是生产者内部打点；不能把 DDS 观察者到包时刻当作 PX4 接收时刻',
                topics={},limits=[],source=str(directory.resolve()))
    for kind,group in topics.items():
        if kind in ('observer_summary','observer_ready'):continue
        result['topics'][kind]=dict(count=len(group),
            observer_wall_gap_ms=stats((b['mono_ns']-a['mono_ns'])/1e6 for a,b in zip(group,group[1:])),
            source_sim_gap_ms=stats((b['source_sim_ns']-a['source_sim_ns'])/1e6 for a,b in zip(group,group[1:])),
            source_age_sim_ms=stats((r['observed_clock_ns']-r['source_sim_ns'])/1e6 for r in group if r.get('observed_clock_ns') is not None))
    def signature(row):
        try:return tuple(float(v) for key in ('p','v','a') for v in row[key])
        except (KeyError,TypeError):return None
    # 仅匹配唯一 p/v/a，静止 hold 重复值不能用最近时间猜测来源。
    planner=defaultdict(list)
    for row in topics['planner']:
        if signature(row) is not None:planner[signature(row)].append(row)
    pairs=[]
    for row in topics['adapter']:
        match=planner.get(signature(row),[])
        if len(match)==1:
            source=match[0]
            pairs.append(dict(planner_sim_ns=source['source_sim_ns'],adapter_sim_ns=row['source_sim_ns'],
                              reference_age_sim_ms=(row['source_sim_ns']-source['source_sim_ns'])/1e6,
                              observer_delta_wall_ms=(row['mono_ns']-source['mono_ns'])/1e6))
    result['planner_adapter']=dict(unique_signature_pairs=len(pairs),pairs=pairs,
        reference_age_sim_ms=stats(p['reference_age_sim_ms'] for p in pairs),
        observer_delta_wall_ms=stats(p['observer_delta_wall_ms'] for p in pairs),
        meaning='参考时间戳年龄与旁路到包先后差；后者可因回调顺序为负，不是精确单向网络延迟')
    if not pairs:result['limits'].append('没有规划到适配器的唯一参考对；未运行规划器或参考重复时，不能评估该段运动期时序。')
    captures=list(directory.glob('hil.pcap'))
    if captures:
        try:
            hil=decode(captures[0]);hil['sensor_to_reply_wall_ms']=stats(p['sensor_to_reply_wall_ms'] for p in hil['pairs'])
            metadata=captures[0].with_suffix('.capture.json')
            if metadata.exists():
                hil['capture']=json.loads(metadata.read_text())
                offsets=[r['wall_ns']-r['mono_ns'] for r in hil['capture']['calibrations']]
                if offsets and max(offsets)-min(offsets)>5e6:
                    result['limits'].append('抓包期间墙钟相对单调时间偏移超过 5 ms，不能可靠解释毫秒级 HIL 延迟。')
                if hil['capture']['kernel_drops']:
                    result['limits'].append('抓包内核有丢包，需先降低观察开销再判断 HIL 匹配率。')
            if not hil['pairs']:result['limits'].append('HIL 未发现相同 time_usec 的请求/回复，不能假定 lockstep 已生效或伪造延迟。')
            result['hil']=hil
        except (ImportError,ValueError) as exc:result['limits'].append('HIL 未解析：'+str(exc))
    else:result['limits'].append('未采集 HIL PCAP，PX4↔AirSim 往返延迟未知。')
    if ulog:
        from pyulog import ULog
        data=ULog(str(ulog),message_name_filter_list=['vehicle_local_position_setpoint'])
        # 内部位置目标通常继承外部位置；唯一、移动目标才能建立关联。
        sent=defaultdict(list)
        for row in topics['dds_input_observed']:
            if all(isinstance(x,(int,float)) for x in row['p']):sent[tuple(round(x,3) for x in row['p'])].append(row)
        delays=[]
        for table in data.data_list:
            if table.name!='vehicle_local_position_setpoint' or table.multi_id:continue
            d=table.data
            for i,stamp in enumerate(d['timestamp']):
                key=tuple(round(float(d[k][i]),3) for k in ('x','y','z'))
                match=sent.get(key,[])
                if len(match)!=1:continue
                delta=(int(stamp)*1000-match[0]['source_sim_ns'])/1e6
                if -.05<=delta<=500:delays.append(delta)
        result['px4_processing_proxy_ms']=stats(delays)
        result['limits'].append('PX4 指标匹配唯一位置目标，表示从源时间戳到内部位置控制目标生成的代理耗时，含控制调度，不是精确 DDS 单向延迟。')
    result['observer_summaries']=topics['observer_summary']
    result['limits'].append('HIL 回复到达之后的 AirSim 电机/物理应用延迟，PCAP 无法直接测得；需结合固定轨迹响应和 ULog，不能归零。')
    (directory/'analysis.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
    print(json.dumps({k:v for k,v in result.items() if k not in ('hil','planner_adapter')},indent=2,ensure_ascii=False))
    if 'hil' in result:print('HIL sensor→reply wall ms:',result['hil']['sensor_to_reply_wall_ms'])
    print('分析：',directory/'analysis.json')
    return result
