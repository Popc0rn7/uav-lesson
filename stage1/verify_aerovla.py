#!/usr/bin/env python3
"""PC：真实 HTTP 固定输入、模型常驻复用和非法请求拒绝检查；不执行动作。"""
import argparse
import concurrent.futures
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request,build_opener,ProxyHandler

ROOT=Path(__file__).resolve().parents[1]


def request(url,path,value=None,timeout=300):
    data=None if value is None else json.dumps(value,allow_nan=False).encode()
    req=Request(url.rstrip('/')+path,data=data,headers={'Content-Type':'application/json'})
    opener=build_opener(ProxyHandler({}))
    try:
        with opener.open(req,timeout=timeout) as response:
            return response.status,json.load(response)
    except HTTPError as error:
        with error:
            return error.code,json.load(error)


def ready(url,timeout):
    status,health=request(url,'/health',timeout=timeout)
    if status!=200 or health.get('status')!='ready' or health.get('model')!='aerovla':
        raise RuntimeError(f'AeroVLA 未就绪：{status} {health}')
    return health


def check_concurrency(url,payload,timeout):
    result={'passed':False,'health_checks':[]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        job=pool.submit(request,url,'/infer',payload,timeout)
        time.sleep(.12)
        while not job.done():
            started=time.monotonic();health=ready(url,min(timeout,5))
            result['health_checks'].append({'elapsed_s':time.monotonic()-started,**health})
            if health['busy']:
                began=time.monotonic();status,body=request(url,'/infer',payload,timeout)
                result.update(competing_status=status,competing_response=body,
                              competing_elapsed_s=time.monotonic()-began)
                break
            time.sleep(.05)
        status,body=job.result(timeout=timeout+5)
        result.update(primary_status=status,primary_response=body)
    result['passed']=result.get('competing_status')==503 and result['primary_status']==200
    return result


def verify(url,payload,timeout=300,concurrency=False):
    report={'passed':False,'url':url,'requests':[],'scope':'HTTP model inference only'}
    try:
        before=ready(url,timeout);report['before']=before
        status,value=request(url,'/infer',{},timeout)
        if status!=400:raise RuntimeError(f'非法请求应返回 400，实际 {status}')
        report['invalid_status']=status
        for _ in range(2):
            started=time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                task=pool.submit(request,url,'/infer',payload,timeout)
                # 真实推理期间另发健康检查，记录实际 busy；短请求不强制观测到 busy。
                health=ready(url,min(timeout,5))
                status,value=task.result(timeout=timeout+5)
            if status!=200:raise RuntimeError(f'推理失败：{status} {value}')
            if not isinstance(value.get('gen_ids'),list) or not isinstance(value.get('text'),str):
                raise ValueError('模型响应缺少 token/text')
            action=value.get('action',{})
            if set(action)!= {'fwd','down','yaw'} or not all(
                type(v) in (int,float) and math.isfinite(v) for v in action.values()):
                raise ValueError('action 不完整或包含非法数值')
            if type(value.get('should_stop')) is not bool:raise ValueError('should_stop 不是布尔值')
            report['requests'].append({'elapsed_s':time.monotonic()-started,'response':value,'health':health})
        after=ready(url,timeout);report['after']=after
        if before.get('pid') is None or before.get('instance_id') is None:
            raise ValueError('health 缺少 pid/instance_id，无法验证实例复用')
        report['instance_reused']=all(before[k]==after[k] for k in ('pid','instance_id'))
        if not report['instance_reused']:raise RuntimeError('测试期间模型服务实例改变')
        if concurrency:
            report['concurrency']=check_concurrency(url,payload,timeout)
            if not report['concurrency']['passed']:
                raise RuntimeError('未观察到真实推理中的健康响应及 503 竞争拒绝')
        report['passed']=True
    except Exception as error:
        report['error']=str(error)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--request',type=Path,default=ROOT/'houmo/models/AeroVLA/samples/request.json')
    parser.add_argument('--report',type=Path,default=ROOT/'artifacts/aerovla/http-smoke.json')
    parser.add_argument('--timeout',type=float,default=300)
    parser.add_argument('--concurrency',action='store_true',help='额外一次真实推理，验证健康并发及 503 拒绝')
    args=parser.parse_args()
    report=verify(args.url,json.loads(args.request.read_text()),args.timeout,args.concurrency)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'report':str(args.report),'error':report.get('error')},ensure_ascii=False))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
