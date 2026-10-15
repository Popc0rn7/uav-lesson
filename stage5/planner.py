"""PC：Qwen VLM 将自然语言任务编译为当前执行器支持的单阶段计划。"""
import argparse
import base64
import json
import math
from pathlib import Path

import requests

from dino_client import configuration, camera_png

SYSTEM = '''你是无人机任务规划者。只输出 JSON 对象，不输出解释或 Markdown。
当前仅支持当前街区中红色车辆/红色方块的后上方跟随，且目标需在初始相机视野内。
执行器使用 DINO 语义确认、红色 RGBD 跟踪和 Jev 决策；没有搜索、绕障或通用目标跟踪技能。
不支持的任务输出 {"unsupported_reason":"原因"}，不得自行改写为跟随红车。
支持的任务输出以下结构，仅一个 stage：
{"version":1,"mission":"用户任务","stages":[{"id":"follow_vehicle","goal":"具体目标",
"skill":"follow_red_vehicle","dino_text":"a red car. a red box.",
"horizontal_distance_m":8,"above_m":2,"duration_s":60,
"completion_criteria":"有效跟随累计达到指定秒数；由 Jev 根据观测进度确认完成",
"failure_criteria":"目标持续丢失、路径受阻或服务故障无法恢复",
"allowed_skills":["hold_course","brake","reacquire"]}]}。
距离、上方高度、时长按用户指令填写，缺省分别8米、2米、给定时长。
dino_text 必须是非空英文检测提示词，针对红车/红方块，不包含飞行动作。
观察输入图片辅助理解，不得根据图片猜测真实距离或捏造已确认目标。
'''


def validate_plan(plan, max_seconds=300):
    if not isinstance(plan,dict):raise ValueError('规划必须是 JSON 对象')
    if plan.get('unsupported_reason'):raise ValueError('规划者不支持任务：'+str(plan['unsupported_reason']))
    stages=plan.get('stages')
    if plan.get('version')!=1 or not isinstance(stages,list) or len(stages)!=1:
        raise ValueError('初版仅支持 version=1、一个 stage')
    stage=stages[0]
    if not isinstance(stage,dict):raise ValueError('stage 必须是 JSON 对象')
    for field in ('id','goal','dino_text','completion_criteria','failure_criteria'):
        if not isinstance(stage.get(field),str) or not 1<=len(stage[field].strip())<=1000:
            raise ValueError('规划缺少有效字段：'+field)
    skills=stage.get('allowed_skills')
    if (stage.get('skill')!='follow_red_vehicle' or not isinstance(skills,list)
            or not all(isinstance(skill,str) for skill in skills)
            or set(skills)!={'hold_course','brake','reacquire'}):
        raise ValueError('规划包含当前执行器未支持的技能')
    for field,lo,hi in (('horizontal_distance_m',3,12),('above_m',1,4),('duration_s',5,max_seconds)):
        value=stage.get(field)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:
            raise ValueError(f'规划参数 {field} 必须在 {lo}～{hi} 内')
    if not isinstance(plan.get('mission'),str) or not plan['mission'].strip():raise ValueError('缺少 mission')
    return plan


def generate(config,task,image,seconds):
    base=config.get('QWEN_BASE_URL','').rstrip('/')
    model=config.get('QWEN_MODEL','')
    if not base or not model:raise ValueError('请在 stage5/.env 配置 QWEN_BASE_URL 与 QWEN_MODEL')
    content=[{'type':'text','text':f'用户任务：{task}\n缺省持续时长及单阶段上限：{seconds} 秒。'},
             {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image).decode()}}]
    headers={'Content-Type':'application/json'}
    if config.get('QWEN_API_KEY'):headers['Authorization']='Bearer '+config['QWEN_API_KEY']
    with requests.Session() as session:
        if config.get('QWEN_PROXY'):
            session.trust_env=False
            session.proxies.update(http=config['QWEN_PROXY'],https=config['QWEN_PROXY'])
        response=session.post(base+'/chat/completions',json=dict(model=model,temperature=0,
            max_tokens=1500,messages=[{'role':'system','content':SYSTEM},{'role':'user','content':content}]),
            headers=headers,timeout=float(config.get('QWEN_TIMEOUT','60')))
    if not response.ok:raise RuntimeError(f'Qwen 规划请求失败 HTTP={response.status_code}；未启动飞行任务')
    try:
        text=response.json()['choices'][0]['message']['content'].strip()
        if text.startswith('```'):text='\n'.join(text.splitlines()[1:-1])
        return validate_plan(json.loads(text),seconds)
    except (KeyError,IndexError,TypeError,AttributeError,json.JSONDecodeError) as exc:
        raise ValueError('Qwen 未返回有效的 JSON 计划；未启动飞行任务') from exc


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',required=True)
    parser.add_argument('--seconds',type=float,default=60)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 5<=args.seconds<=300:parser.error('seconds 须为5～300')
    config=configuration()
    try:
        image,_=camera_png(config['STAGE5_RGB_URL'],2)
        plan=generate(config,args.task,image,args.seconds)
        with args.output.open('x') as output:json.dump(plan,output,ensure_ascii=False,indent=2)
        print(f'Qwen plan: {args.output}')
    except requests.RequestException as exc:raise SystemExit('Qwen 网络请求失败：'+type(exc).__name__) from None
    except (ValueError,RuntimeError,OSError) as exc:raise SystemExit(str(exc)) from None


if __name__=='__main__':main()
