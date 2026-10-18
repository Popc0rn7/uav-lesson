"""Bounded smooth references and response cancellation, independent of ROS."""
import math


class Motion:
    def __init__(self, start, target, yaw, target_yaw, started, config):
        from stage4.contracts import wrap
        self.start,self.target = list(start),list(target)
        self.yaw,self.dyaw,self.started = yaw,wrap(target_yaw-yaw),started
        distance = math.dist(start,target)
        dz=target[2]-start[2]
        vertical_speed=config.get('vertical_speed_down_m_s',1.) if dz>0 else config.get('vertical_speed_up_m_s',2.)
        self.duration = max(.1, 1.875*distance/config['speed_m_s'],
                            math.sqrt(5.78*distance/config['acceleration_m_s2']),
                            1.875*abs(dz)/vertical_speed,
                            math.sqrt(5.78*abs(dz)/config.get('vertical_acceleration_m_s2',3.)),
                            1.875*abs(self.dyaw)/config['yaw_rate_rad_s'])

    def sample(self, seconds):
        u = max(0., min(1., (seconds-self.started)/self.duration))
        s = 10*u**3-15*u**4+6*u**5
        ds = (30*u*u-60*u**3+30*u**4)/self.duration
        dds = (60*u-180*u*u+120*u**3)/self.duration**2
        delta = [b-a for a,b in zip(self.start,self.target)]
        return ([a+s*d for a,d in zip(self.start,delta)], [ds*d for d in delta],
                [dds*d for d in delta], self.yaw+s*self.dyaw, ds*self.dyaw, u >= 1.)


class InferenceGate:
    def __init__(self):
        self.pending = None
        self.cancelled = False

    def begin(self, request_id):
        if self.cancelled or self.pending is not None:
            raise RuntimeError('Inference cancelled or already pending')
        self.pending = request_id

    def accept(self, request_id):
        if self.cancelled or self.pending != request_id: return False
        self.pending = None
        return True

    def cancel(self):
        self.cancelled = True
        self.pending = None
