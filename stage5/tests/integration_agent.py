#!/usr/bin/env python3
"""PC手动集成测试：模拟Qwen/Jev协议，使用真实DINO、相机和已悬停的Stage5 PX4。
运行 .venv/bin/python stage5/tests/integration_agent.py；不会调用付费模型。
"""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

HERE = Path(__file__).resolve().parents[1]


def follow(id='follow', budget=1, above=2, duration=4):
    return dict(id=id,goal='跟随红车',skill='follow_red_vehicle',dino_text='a red car. a red box.',
        horizontal_distance_m=8,above_m=above,duration_s=duration,
        completion_criteria='有效跟随达到指定时长',failure_criteria='无法跟踪',
        allowed_skills=['hold_course','brake','reacquire'],allocation={'budget':budget,'timeout':25})


class Handler(BaseHTTPRequestHandler):
    reviews=[];states=[];purposes=[]
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path.endswith('/chat/completions'):
            data=json.loads(payload['messages'][1]['content'][0]['text']);purpose=data['purpose']
            Handler.purposes.append(purpose)
            if purpose=='plan':
                observe=dict(id='observe',goal='观察并确认红车',skill='observe_target',dino_text='a red car. a red box.',
                    completion_criteria='可靠确认红车',failure_criteria='无法确认',allowed_skills=['brake','reacquire'],
                    allocation={'budget':4,'timeout':15})
                result=dict(version=2,mission='协议测试：观察后跟随',stages=[observe,follow()])
            elif purpose=='summary':result={'summary':'协议测试结束；模型为本地模拟接口。'}
            else:
                Handler.reviews.append(data)
                count=len(Handler.reviews)
                result=({'action':'accept'} if count in (1,5) else
                        {'action':'redo','allocation':{'budget':2,'timeout':20}} if count==2 else
                        {'action':'modify_stage','stage':follow(budget=2,above=2.2)} if count==3 else
                        {'action':'modify_plan','stages':[follow('final',8,2.2)]})
            body={'choices':[{'message':{'content':json.dumps(result)}}]}
        else:
            state=payload['state'];state=json.loads(state) if isinstance(state,str) else state
            Handler.states.append(copy.deepcopy(state))
            visible=state['observed']['target_visible'];s=state['stage']
            done=visible and (s['skill']=='observe_target' or state['progress']['valid_follow_s']>=s['duration_s'])
            maneuver='hold_course' if s['skill']=='follow_red_vehicle' else 'brake'
            body=dict(model='protocol-test-only',usage=dict(input_tokens=0,output_tokens=0),answers=dict(
                maneuver=dict(type='choice',choice=maneuver,confidence=.9,probabilities={maneuver:1}),
                stage_reason=dict(type='choice',choice='achieved' if done else 'approaching' if visible else 'observing',confidence=.9,probabilities={}),
                stage_status=dict(type='choice',choice='done' if done else 'running',confidence=.9,
                                  probabilities={'done' if done else 'running':1}),
                risk=dict(type='score',score=0,confidence=.9,legend={'0':'clear'},probabilities={'0':1})))
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(json.dumps(body).encode())
    def log_message(self,*args):pass


def main():
    root=Path(tempfile.mkdtemp(prefix='stage5-agent-protocol-'))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    env={k:v for k,v in os.environ.items() if 'proxy' not in k.lower()}
    env.update(QWEN_BASE_URL=base+'/vlm/v1',QWEN_MODEL='protocol-test-only',QWEN_API_KEY='',QWEN_PROXY='',
               TYPESAFE_BASE_URL=base+'/jev',TYPESAFE_API_KEY='protocol-test-only',JEV_PROXY='')
    try:
        result=subprocess.run([sys.executable,str(HERE/'mission.py'),'--budget','8','--timeout','90',
            '--output',str(root/'mission')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        print(result.stdout,flush=True);(root/'console.log').write_text(result.stdout)
        assert result.returncode==0, '任务应由最后一次accept完成'
        mission=root/'mission';ledger=json.loads((mission/'ledger.json').read_text())
        assert Handler.purposes==['plan','review','review','review','review','review','summary']
        assert ledger['qwen_execution_calls']==6 and ledger['qwen_summary_calls']==1
        reports=[json.loads(path.read_text()) for path in sorted(mission.glob('attempt-*/report.json'))]
        assert len(reports)==5 and reports[1]['status']=='budget_exhausted'
        assert all(row['plan_revision']>=1 for row in reports)
        assert any(row['progress']['enabled_follow_s']>0 for row in reports)
        assert len(list(mission.glob('plan-*.json')))==4
        (root/'protocol.json').write_text(json.dumps({'mock_models':True,'purposes':Handler.purposes,
            'jev_requests':len(Handler.states),'reviews':Handler.reviews},ensure_ascii=False,indent=2))
        print(f'PASS protocol integration: {root}',flush=True)
    finally:server.shutdown()


if __name__=='__main__':main()
