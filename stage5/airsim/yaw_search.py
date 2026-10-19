"""原地偏航：角速度受限，仅限制角速度和指令领先量，不规定扫描圈数或任务结束条件。"""
import math


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def yaw_of(own):
    from follow import rotation
    r = rotation(own['q'])
    return math.atan2(r[1, 0], r[0, 0])


class YawScan:
    def __init__(self, yaw, rate=math.radians(20)):
        self.start = self.last = self.command = yaw
        self.rate, self.travel = rate, 0.
        self.active = False

    def pause(self, yaw):
        self.active = False
        self.last = self.command = yaw

    def step(self, yaw, dt):
        if self.active:
            self.travel = max(0., self.travel+wrap(yaw-self.last))
        self.active = True; self.last = yaw
        # 指令最多领先实测航向15度，仿真变慢时不堆积大幅跳转。
        advance = min(self.rate*max(0., min(dt, .1)), max(0., math.radians(15)-wrap(self.command-yaw)))
        self.command = wrap(yaw+max(0., wrap(self.command-yaw))+advance)
        return self.command
