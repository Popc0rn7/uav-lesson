"""AeroVLA EvalBatchState rules, isolated from its Torch/evaluation runtime.

Source: closeloop_util.py, env_uav.py, assist.py (see NOTICE.md).
"""
from collections import deque
import math

DEPTH_CAMERAS=('FrontCamera','LeftCamera','RightCamera','RearCamera','DownCamera')


def depth_proximity(frames):
    """Match clip(meters,0,100)/100*255 -> uint8 <=1, fraction >0.1."""
    fractions={}
    for name,frame in zip(DEPTH_CAMERAS,frames,strict=True):
        values=frame['image_data_float']; size=frame['width']*frame['height']
        if not size or len(values)!=size: raise ValueError(f'Missing depth image: {name}')
        if any(not math.isfinite(v) for v in values): raise ValueError(f'Invalid depth image: {name}')
        fractions[name]=sum(int(min(100.,max(0.,v))/100*255)<=1 for v in values)/size
    return fractions


class Evaluation:
    def __init__(self,target,success_distance=20.):
        self.target=list(target); self.threshold=success_distance
        self.distances=deque(maxlen=10); self.last_position=None
        self.stuck_count=0; self.oracle_success=False; self.early_end=False
        self.success=False; self.reason=None; self.legacy_collision=False

    def initialize(self,position):
        self.distances.append(math.dist(position,self.target))

    def after_action(self,position,depth_fractions):
        distance=math.dist(position,self.target)
        self.oracle_success |= distance<self.threshold
        # The source's first post-action update compares the position to itself.
        previous=position if self.last_position is None else self.last_position
        self.stuck_count=self.stuck_count+1 if math.dist(position[:2],previous[:2])<.05 else 0
        self.last_position=list(position); self.distances.append(distance)
        if any(v>.1 for v in depth_fractions.values()): self.reason='depth proximity'
        elif self.stuck_count>15: self.reason='stuck'
        elif len(self.distances)==10 and all(b>=a for a,b in zip(self.distances,list(self.distances)[1:])):
            self.reason='target distance nondecreasing'
        self.legacy_collision=self.reason is not None
        return self.reason

    def stop(self,position):
        distance=math.dist(position,self.target)
        self.oracle_success |= distance<self.threshold
        self.early_end=distance>self.threshold
        self.success=distance<=self.threshold and not self.early_end and not self.legacy_collision
        # API STOP always lands; do not reproduce the old far-STOP continuation.
        self.reason='model requested stop' if self.success else 'early end: model stop too far from target'
        return self.reason

    def snapshot(self):
        return dict(success=self.success,oracle_success=self.oracle_success,early_end=self.early_end,
                    stuck_count=self.stuck_count,distance_history_m=list(self.distances),
                    legacy_collision=self.legacy_collision,reason=self.reason,
                    position_source='PX4 estimated world NED; no simulator truth feedback')
