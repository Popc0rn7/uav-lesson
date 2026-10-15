"""仅 Stage 5 Gazebo：模型等待期间允许3秒仿真推进，随后暂停，退出必恢复。"""
import subprocess
import time

from agent_errors import FatalControl
from dino_client import raw_frame


def world_pause(paused):
    command = [
        'docker', 'exec', 'uav-stage5-gazebo', 'gz', 'service',
        '-s', '/world/stage5_street/control',
        '--reqtype', 'gz.msgs.WorldControl', '--reptype', 'gz.msgs.Boolean',
        '--timeout', '2000', '--req', 'pause: ' + str(paused).lower(),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=4)
        if result.returncode or 'data: true' not in result.stdout:
            raise RuntimeError('world control not acknowledged')
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        action = 'pause' if paused else 'resume'
        raise FatalControl(f'Gazebo {action} failed: {type(exc).__name__}') from None


class SimulationWait:
    """一次Qwen请求拥有一个等待窗口；finish可重复调用以清理暂停。"""

    def __init__(self, rgb_url, allowance_s=3., sample=None, control=world_pause,
                 clock=time.monotonic):
        self.sample = sample or (lambda: raw_frame(rgb_url, .7)[0]['sim_time'])
        self.control, self.clock = control, clock
        self.allowance_s = allowance_s
        self.active = self.paused = False
        self.started_sim = None
        self.last_sample = 0
        self.runtime = None
        self.event = lambda *args, **kwargs: None

    def begin(self, runtime, event):
        if self.active or self.paused:
            raise FatalControl('previous simulation wait not restored')
        self.runtime, self.event = runtime, event
        try:
            self.started_sim = self.sample()
        except Exception:
            raise FatalControl('Gazebo clock unavailable before Qwen request') from None
        self.active = True
        self.last_sample = self.clock()
        self.event('qwen_sim_window', allowance_sim_s=self.allowance_s,
                   sim_time=self.started_sim)

    def tick(self):
        if not self.active or self.paused or self.clock() - self.last_sample < .1:
            return
        self.last_sample = self.clock()
        try:
            stamp = self.sample()
        except Exception:
            raise FatalControl('Gazebo clock unavailable during Qwen request') from None
        if stamp - self.started_sim < self.allowance_s:
            return
        # 在请求暂停之前登记所有权；确认失败也由finally恢复。
        self.paused = True
        if hasattr(self.runtime, 'simulation_pause_changed'):
            self.runtime.simulation_pause_changed(True)
        self.control(True)
        self.paused_sim = stamp
        self.event('simulation_paused', sim_time=stamp,
                   advanced_sim_s=stamp - self.started_sim)

    def finish(self):
        if self.paused:
            self.control(False)
            self.paused = False
            if hasattr(self.runtime, 'simulation_pause_changed'):
                self.runtime.simulation_pause_changed(False)
            until = self.clock() + 2
            while self.clock() < until:
                try:
                    restored = self.sample()
                    if restored > getattr(self, 'paused_sim', self.started_sim):
                        break
                except Exception:
                    pass
                time.sleep(.03)
            else:
                self.active = False
                raise FatalControl('Gazebo resume acknowledged but no fresh advancing clock')
            self.event('simulation_resumed', sim_time=restored)
        self.active = False
