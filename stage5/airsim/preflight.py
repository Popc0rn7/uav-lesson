"""任务前检查：只读现场；显式调用时各做一次最小模型请求。"""
from concurrent.futures import ThreadPoolExecutor
import time

import requests

from decision_client import DecisionClient, Choice
from dino_client import DinoClient, paired_frames, camera_png


def check_models(config, rgb):
    def jev():
        client = DecisionClient(config, 15)
        try:
            result = client.system_one(state={'test': 'synthetic readiness probe', 'target_visible': False},
                model=config.get('JEV_MODEL') or ('jev-decision' if client.backend == 'vllm' else 'jev-latest'),
                questions={'action': Choice(instructions='No valid target. Choose hold.', criteria={'hold': 'hold position', 'move': 'move'})})
            return dict(ok=result.answers['action'].choice == 'hold', backend=client.backend)
        finally:
            client.close()

    def dino():
        image, _ = camera_png('', 1, rgb)
        response, elapsed = DinoClient(config['DINO_DETECT_URL'], 15).detect(image, text='a pickup truck.')
        return dict(ok=isinstance(response.get('detections'), list) and response.get('width') == rgb[0]['width']
                    and response.get('height') == rgb[0]['height'], elapsed_s=elapsed)

    def qwen():
        with requests.Session() as session:
            session.trust_env = False
            if config.get('QWEN_PROXY'):
                session.proxies.update(http=config['QWEN_PROXY'], https=config['QWEN_PROXY'])
            headers = {'Authorization': 'Bearer '+config['QWEN_API_KEY']} if config.get('QWEN_API_KEY') else {}
            response = session.post(config['QWEN_BASE_URL'].rstrip('/')+'/chat/completions', headers=headers,
                json=dict(model=config['QWEN_MODEL'], temperature=0, max_tokens=16, enable_thinking=False,
                          messages=[{'role': 'user', 'content': 'Readiness test. Reply only OK.'}]), timeout=15)
            response.raise_for_status()
            body = response.json()
            return dict(ok=bool(body['choices'][0]['message']['content'].strip()))

    def run(item):
        name, probe = item; start = time.monotonic()
        try:
            result = probe()
        except Exception as exc:
            result = dict(ok=False, error_type=type(exc).__name__)
        return name, dict(**result, wall_s=time.monotonic()-start)

    with ThreadPoolExecutor(max_workers=3) as pool:
        return dict(pool.map(run, [('dino', dino), ('jev', jev), ('qwen', qwen)]))


def check(state, config, *, models=True):
    from stage5.airsim.runtime import inspect, call
    result = inspect(state)
    report = dict(run_id=state['run_id'], transport_ready=result['ready'], model_services_ready=False, ready=False)
    if not result['ready']:
        report['reason'] = 'AirSim/PX4/RGBD 链路未就绪；先恢复场景并重新 up'
        return report
    try:
        convoy = call(state['config'], 'simGetConvoyStatus')
        import json
        convoy = json.loads(convoy)
        report['convoy_ready'] = bool(convoy.get('ok') and convoy.get('state') in ('idle', 'stopped')
                                      and len(convoy.get('vehicles', [])) == 3
                                      and all(v.get('available') for v in convoy['vehicles']))
        telemetry = result['sensors']['telemetry']
        report['disarmed'] = telemetry.get('armed') is False
        from stage5.airsim.runtime import px4
        vehicle = px4(state, 'listener', 'vehicle_status').stdout
        report['preflight_pass'] = 'pre_flight_checks_pass: True' in vehicle
        rgb, depth = paired_frames(config['STAGE5_RGB_URL'], config['STAGE5_DEPTH_URL'], 2, .05)
        report['capture_pose_ready'] = bool(rgb[0].get('px4_pose'))
        report['camera_source'] = rgb[0].get('source')
        if models:
            report['models'] = check_models(config, rgb)
            report['model_services_ready'] = all(v['ok'] for v in report['models'].values())
        report['ready'] = all(report.get(k) for k in ('transport_ready', 'convoy_ready', 'disarmed',
            'preflight_pass', 'capture_pose_ready', 'model_services_ready')) and report['camera_source'] == 'airsim'
    except Exception as exc:
        report.update(reason='preflight check failed', error_type=type(exc).__name__)
    return report
