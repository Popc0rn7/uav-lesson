#!/usr/bin/env python3
"""PC：HDC 核验 worker，Docker ROS 验证跨以太网的 Stage 1 文本往返。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from uav_hdc import shell


def health(target):
    probe="import json; from urllib.request import build_opener,ProxyHandler; h=json.load(build_opener(ProxyHandler({})).open('http://127.0.0.1:8080/health',timeout=3)); print(json.dumps(h))"
    import shlex
    data=json.loads(shell(target,'python3 -B -c '+shlex.quote(probe)))
    if data.get('status')!='ready' or data.get('model')!='qwen3.6-35b-a3b' or type(data.get('worker_pid')) is not int:
        raise RuntimeError('模型服务未就绪或 worker/model 不匹配')
    pid=data['worker_pid']
    executable=shell(target,'readlink -f /proc/'+str(pid)+'/exe')
    if executable!='/data/local/workspace/stage1/qwen_infer/qwen_ohos_infer':
        raise RuntimeError('8080 worker 不属于课程 Stage 1 部署')
    data['start_ticks']=shell(target,"cat /proc/"+str(pid)+"/stat").rsplit(')',1)[1].split()[19]
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',required=True)
    parser.add_argument('--dds-profile',type=Path,help='PC 显式接口/对端 Fast DDS 配置')
    parser.add_argument('--image',default='osrf/ros:humble-desktop-jammy')
    parser.add_argument('--report',type=Path,default=ROOT/'artifacts/stage1-validation/result.json')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        manifest=Path(temporary)/'checks.json'
        manifest.write_text(json.dumps(dict(checks=[dict(kind='tool',tool='hdc',version_option='-v'),
            dict(kind='tool',tool='docker',version_option='--version'),dict(kind='hdc-identity',target=args.target)])))
        subprocess.run([sys.executable,str(ROOT/'skills/hdc-master/scripts/preflight.py'),
                        '--manifest',str(manifest),'--timeout','15'],check=True)
    report=dict(passed=False,started_at=time.time(),target=args.target,image=args.image)
    try:
        subprocess.run(['docker','image','inspect',args.image],check=True,capture_output=True,text=True)
        report['before']=health(args.target)
        # No pull, API keys or HDC forwarding. DDS uses the actual Ethernet network.
        result=subprocess.run(['docker','run','--pull','never','--rm','--network','host',
            '-e','ROS_DOMAIN_ID=10','-e','ROS_LOCALHOST_ONLY=0','-e','RMW_IMPLEMENTATION=rmw_fastrtps_cpp',
            '--mount',f'type=bind,source={ROOT},target=/course,readonly',
            *(['--mount',f'type=bind,source={args.dds_profile.resolve()},target=/course-dds.xml,readonly',
               '-e','FASTRTPS_DEFAULT_PROFILES_FILE=/course-dds.xml'] if args.dds_profile else []),
            '--entrypoint','bash',args.image,'-lc',
            'source /opt/ros/humble/setup.bash && python3 -B /course/stage1/chat_probe.py'],
            capture_output=True,text=True,timeout=750)
        report.update(stdout=result.stdout,stderr=result.stderr)
        result.check_returncode()
        lines=[line.removeprefix('STAGE1_RESULT:') for line in result.stdout.splitlines() if line.startswith('STAGE1_RESULT:')]
        if len(lines)!=1:raise RuntimeError('缺少唯一 ROS 验收结果')
        report['chat']=json.loads(lines[0])
        report['after']=health(args.target)
        report['worker_reused']=all(report['before'][k]==report['after'][k] for k in ('worker_pid','start_ticks'))
        report['passed']=report['chat']['passed'] and report['worker_reused']
        if not report['passed']:raise RuntimeError('worker 未复用或聊天检查失败')
    except Exception as exc:
        report['error']=str(exc)
        raise
    finally:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False))
        print('报告：'+str(args.report))


if __name__=='__main__':main()
