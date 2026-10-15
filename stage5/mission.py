#!/usr/bin/env python3
"""PC：Qwen任务闭环；预算约束、阶段执行/验收、计划修订与最终总结。"""
import argparse
import json
import math
from pathlib import Path
import signal
import tempfile

from agent_contracts import upgrade_legacy
from dino_client import configuration
from qwen_agent import QwenAgent
from task_runner import TaskRunner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', help='自然语言任务；复用计划时缺省使用计划中的mission')
    parser.add_argument('--seconds', type=float, default=60, help='未指定时长时给规划者的缺省跟随时长')
    parser.add_argument('--budget', type=int, default=10, help='Qwen执行调用上限；另有预算外总结1次')
    parser.add_argument('--timeout', type=float, default=300, help='整个任务的墙钟秒数，不含最终总结')
    parser.add_argument('--target-speed', type=float, default=.7)
    parser.add_argument('--jev-budget', type=int, default=40, help='只用于适配显式传入的旧版plan，不约束在线Qwen分配')
    parser.add_argument('--plan', type=Path, help='复用已有计划，跳过初始Qwen规划；验收仍由Qwen负责')
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if (args.budget < 1 or not all(math.isfinite(v) and v > 0 for v in (args.timeout,args.seconds))
            or not .1 <= args.target_speed <= 1 or args.jev_budget < 1):
        parser.error('budget须为正整数；timeout/seconds为有限正数；target-speed为0.1～1')
    output = args.output or Path(tempfile.mkdtemp(prefix='stage5-mission-'))
    if args.output: output.mkdir(parents=True,exist_ok=False)
    print(f'Mission evidence: {output}',flush=True)
    def interrupt(signum, frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    try:
        config = configuration()
        model = QwenAgent(config)
        initial_plan = upgrade_legacy(json.loads(args.plan.read_text()),args.jev_budget,args.seconds) if args.plan else None
        # 延迟导入，纯生命周期测试不依赖飞行硬件。
        from agent_runtime import FlightRuntime, ReadOnlyRuntime
        from simulation_wait import SimulationWait
        factory = ((lambda deadline: ReadOnlyRuntime(config)) if args.plan_only else
                   (lambda deadline: FlightRuntime(config,output,deadline,args.target_speed)))
        task = args.task or (initial_plan['mission'] if initial_plan else '跟随红色车辆，在车尾后方8米、上方2米持续跟随。')
        runner = TaskRunner(task,model,factory,output,args.budget,args.timeout,args.seconds,
            initial_plan,args.plan_only,request_timeout=float(config.get('QWEN_TIMEOUT','120')),
            summary_timeout=float(config.get('QWEN_SUMMARY_TIMEOUT','30')),
            simulation=SimulationWait(config.get('STAGE5_RGB_URL','http://127.0.0.1:8189/rgb')))
        from mission_registry import register
        register(output)
        return runner.run()
    except (ValueError,OSError) as exc:
        print(str(exc),flush=True); return 1


if __name__ == '__main__': raise SystemExit(main())
