"""Merge HTTP and server timing records and produce a readable latency report."""
import argparse
from collections import Counter
import json
from pathlib import Path
from benchmark_latency import summarize


STAGES = [
 ('client_input_base64_ms', '客户端输入 Base64'),
 ('client_request_json_ms', '客户端请求 JSON'),
 ('request_body_read_ms', '板端接收请求体'),
 ('request_json_parse_ms', '板端解析请求 JSON'),
 ('image_base64_decode_ms', '板端解码输入 Base64'),
 ('image_decode_ms', '图片解码'),
 ('image_color_and_geometry_ms', 'RGB 转换与尺寸计算'),
 ('image_resize_ms', '双线性缩放'),
 ('image_normalize_pad_ms', '归一化与 padding'),
 ('text_tokenize_ms', 'BERT 分词'),
 ('text_masks_ms', '文本 mask 与 position'),
 ('input_cast_write_ms', '输入 dtype 转换与写文件'),
 ('native_input_allocate_read_ms', '原生输入分配与读文件'),
 ('native_set_input_ms', 'TCIM SetInput'),
 ('native_run_sync_ms', 'TCIM Run(true) 同步执行'),
 ('native_get_output_ms', 'TCIM GetOutput'),
 ('native_output_allocate_ms', '原生输出分配及其他'),
 ('native_output_write_ms', '原生输出写文件'),
 ('output_read_cast_ms', 'Python 输出读文件与转换'),
 ('box_score_label_ms', '分数/框/标签解码'),
 ('overlay_draw_ms', '绘制框与文字'),
 ('overlay_png_encode_ms', '叠加图 PNG 编码'),
 ('overlay_base64_encode_ms', '叠加图 Base64 编码'),
 ('response_json_serialize_ms', '响应 JSON 序列化'),
 ('response_socket_write_ms', '响应 socket 写入（可能与下载重叠）'),
 ('client_response_json_ms', '客户端响应 JSON 解析'),
 ('client_overlay_base64_decode_ms', '客户端叠加图 Base64 解码'),
]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--report', type=Path, action='append', required=True)
    cli.add_argument('--server-log', type=Path, required=True)
    cli.add_argument('--output-dir', type=Path, required=True)
    cli.add_argument('--canvas', type=int, nargs=2, default=(800,1344), metavar=('HEIGHT','WIDTH'))
    args = cli.parse_args()
    profiles, startups = {}, []
    for line in args.server_log.read_text().splitlines():
        if 'DINO_PROFILE ' in line:
            record = json.loads(line.split('DINO_PROFILE ',1)[1]); profiles[record['profile_id']] = record
        if 'DINO_STARTUP ' in line:
            startups.append(json.loads(line.split('DINO_STARTUP ',1)[1]))
    reports = [json.loads(p.read_text()) for p in args.report]
    scenarios = []
    for report in reports:
        assert report['before']['worker_pid']==report['after']['worker_pid']
        for scenario in report['scenarios']:
            assert len(scenario['rows'])==report['repeat']
            assert len(scenario['warmups'])==report['warmup']
            for row in scenario['rows']+scenario['warmups']:
                record = profiles[row['profile_id']]
                assert record['response_bytes']==row['response_bytes']
                for key in ('response_socket_write_ms','server_handler_ms'):
                    row['metrics_ms'][key] = record['timings_ms'][key]
                m = row['metrics_ms']
                assert all(v>=0 for v in m.values()), row['profile_id']
                measured = sum(m[k] for k in ('request_body_read_ms','request_json_parse_ms','request_validate_ms','image_base64_decode_ms','image_decode_ms','temp_create_ms','prepare_total_ms','worker_roundtrip_ms','finish_total_ms','temp_cleanup_ms'))
                assert abs(m['server_before_json_ms']-measured)<5
                m['worker_ipc_profile_overhead_ms'] = m['worker_roundtrip_ms']-m['native_total_ms']
                m['python_prepare_other_ms'] = m['prepare_total_ms']-sum(m[k] for k in ('image_color_and_geometry_ms','image_resize_ms','image_normalize_pad_ms','text_tokenize_ms','text_masks_ms','input_cast_write_ms'))
            scenario['summary_ms']=summarize(scenario['rows'])
            scenario['transport']=report['transport']
            scenario['repeat']=report['repeat']; scenario['warmup']=report['warmup']
            scenarios.append(scenario)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    merged={'startups':startups,'scenarios':scenarios,'definitions':{r['transport']:r['definition'] for r in reports}}
    (args.output_dir/'latency_merged.json').write_text(json.dumps(merged,indent=2))
    def metric(s,k,stat='mean'):
        return s['summary_ms'].get(k,{}).get(stat,0.)
    def label(s):
        return s['name']+(' +叠加图' if s['overlay'] else ' 仅框')
    dimensions={(r['width'],r['height']) for s in scenarios for r in s['rows']}
    only_640 = dimensions == {(640,360)}
    title = '# Grounding DINO 640×360 端到端时延实测' if only_640 else '# Grounding DINO 板端端到端时延实测'
    scope = ('用户最终确定输入为 640×360。本报告只统计该尺寸；HMM 固定输入为 800×1344，板端先将图像放大到 1333×750，再补齐画布。PNG 与 JPEG 来自同一张缩小后的样例图，JPEG 质量 95。' if only_640 else '1333×750 样例可跳过缩放；3420×2214 样例需要缩放。JPEG 质量为 95。')
    if only_640 and tuple(args.canvas)==(360,640):
        scope='输入图像与HMM画布均为640×360（宽×高），跳过缩放，无需padding。PNG与JPEG来自同一张样例图，JPEG质量95。'
    lines=[title,'',
        '模型常驻、并发 1、顺序请求、无输入缓存；未修改 CPU/NPU 频率或系统服务。每场景单独预热，统计不含预热。',
        scope,'',
        '## 客户端完整时延','',
        '计时从内存中压缩图片的 Base64 编码前开始，至完整响应 JSON 解析和叠加图 Base64 解码结束。包含 HTTP 建连、上传、板端处理、下载；不含读取源文件、相机采集、输入 JPEG/PNG 编码、显示、保存结果文件。每请求新建 HTTP 连接。','',
        '| 通道 | 场景 | 预热/次数 | 平均 ms | P50 | P90 | P95 | 最小 | 最大 | 标准差 |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    if only_640:
        primary=[s for s in scenarios if s['transport']=='usb-hdc']
        jpeg=next((s for s in primary if 'jpeg' in s['name'] and not s['overlay']),None)
        png=next((s for s in primary if 'png' in s['name'] and not s['overlay']),None)
        conclusions=[]
        if jpeg:
            conclusions += [f"JPEG 仅框平均 {metric(jpeg,'client_total_ms'):.2f} ms，其中同步 Run {metric(jpeg,'native_run_sync_ms'):.2f} ms、缩放 {metric(jpeg,'image_resize_ms'):.2f} ms、归一化与 padding {metric(jpeg,'image_normalize_pad_ms'):.2f} ms。"]
        if png:
            conclusions += [f"PNG 仅框平均 {metric(png,'client_total_ms'):.2f} ms。"]
        for off in [s for s in primary if not s['overlay']]:
            on=next((s for s in primary if s['name']==off['name'] and s['overlay']),None)
            if on: conclusions += [f"{off['name']} 开启叠加图的平均增量为 {metric(on,'client_total_ms')-metric(off,'client_total_ms'):.2f} ms。"]
        if jpeg and png:
            jc=sorted(set(r['detections'] for r in jpeg['rows'])); pc=sorted(set(r['detections'] for r in png['rows']))
            if jc!=pc: conclusions += [f"同一张 640×360 样例中，PNG 检出数量 {pc}，JPEG 质量95检出数量 {jc}，存在目标检出差异。"]
        lines[4:4]=[' '.join(conclusions),'']
    for s in scenarios:
        m=s['summary_ms']['client_total_ms']
        lines.append(f"| {s['transport']} | {label(s)} | {s['warmup']}/{s['repeat']} | "+' | '.join(f'{m[k]:.2f}' for k in ('mean','p50','p90','p95','min','max','stdev'))+' |')
    lines += ['', 'P95 使用线性插值的样本分位数；样本数有限，不代表长期尾延迟上界。', '', '## 请求与响应大小', '',
              '| 通道 | 场景 | 输入文件 KiB | 请求体 KiB | 响应体 KiB | 检测数量（次数） |', '|---|---|---:|---:|---:|---|']
    for s in scenarios:
        rows=s['rows']; counts=dict(Counter(r['detections'] for r in rows))
        lines.append(f"| {s['transport']} | {label(s)} | {s['image_bytes']/1024:.1f} | {sum(r['request_bytes'] for r in rows)/len(rows)/1024:.1f} | {sum(r['response_bytes'] for r in rows)/len(rows)/1024:.1f} | {counts} |")
    for transport in dict.fromkeys(s['transport'] for s in scenarios):
        selected=[s for s in scenarios if s['transport']==transport]
        for overlay in (False,True):
            group=[s for s in selected if s['overlay']==overlay]
            if not group: continue
            lines += ['',f"## {transport} 分阶段均值（{'含叠加图' if overlay else '仅检测框'}，ms）",'',
                      '| 阶段 | '+' | '.join(s['name'] for s in group)+' |',
                      '|---|'+'---:|'*len(group)]
            for key,name in STAGES:
                lines.append('| '+name+' | '+' | '.join(f'{metric(s,key):.2f}' for s in group)+' |')
            for key,name in [('worker_ipc_profile_overhead_ms','worker IPC/计时文件/调度额外开销'),('python_prepare_other_ms','Python 预处理其他开销'),('temp_create_ms','创建请求临时目录'),('temp_cleanup_ms','清理请求临时目录'),('server_to_headers_ms','板端处理至发送响应头（汇总）'),('http_roundtrip_ms','客户端 HTTP 往返至响应体收完（汇总）'),('client_total_ms','客户端完整端到端（汇总）')]:
                lines.append('| '+name+' | '+' | '.join(f'{metric(s,key):.2f}' for s in group)+' |')
    lines += ['', '## 计时口径与限制','',
        '- `native_run_sync_ms` 是同步 TCIM Run(true) 的主机墙钟时间，包含 runtime 调度与等待，不是硬件事件测得的纯 NPU kernel 时间。SetInput/GetOutput 单独计时。',
        '- Python 与 C++ 的文件读写通过系统页缓存完成；没有 fsync，不是存储介质持久写入延迟。',
        '- socket 写入与客户端下载可能重叠，不能把两端相同区间重复相加。Loopback 与 USB 客户端运行在不同 CPU 上，二者差值不能直接称为纯网络延迟。',
        '- 旧 `elapsed_ms` 从图片解码完成后开始，到临时目录清理结束；排除了接收请求、JSON/Base64 解析、图像解码以及响应序列化与传输。',
        '- 本计时版本有少量计时与原生侧文件开销，`profile=true` 另增加返回字段和日志；原始检测输出已与无计时版本逐项核对一致。',
        '- 本次只做单并发稳态测量，忙时请求返回 503，不做排队；不等同于多客户端吞吐测试。' ,
        ('- 本报告分辨率固定为 640×360，PNG/JPEG 对照来自同一源图。JPEG 为有损编码，检测数量也记录在表中；叠加图开关使用同一压缩输入。' if only_640 else '- 不同尺寸包含不同场景与检测数量，跨图对比不是只改变分辨率的严格 A/B；PNG/JPEG 对照使用同一源图，叠加图开关也使用同一输入。'),
        '- 启动数据来自本次重启；ready_after_worker_start_ms 从创建原生 worker 前开始计时，不含 Python 解释器启动及模块导入。操作系统文件缓存未清除，不是断电冷启动。','',
        '## 本次启动（ms）','', '```json',json.dumps(startups,indent=2),'```','',
        '原始客户端报告：'+ '、'.join('`'+p.name+'`' for p in args.report)+'；关联后的完整记录为 `latency_merged.json`，服务日志为 `service_profile.log`。']
    (args.output_dir/'LATENCY_REPORT.md').write_text('\n'.join(lines)+'\n')
    print(args.output_dir/'LATENCY_REPORT.md')


if __name__=='__main__':
    main()
