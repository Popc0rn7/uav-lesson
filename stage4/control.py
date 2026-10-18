"""ROS Docker: continuous PX4 Offboard plus asynchronous AeroVLA task execution."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import math
from pathlib import Path
import time

from PIL import Image as PILImage
import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from px4_msgs.msg import (VehicleOdometry, VehicleStatus, FailsafeFlags,
                         VehicleCommand, OffboardControlMode, TrajectorySetpoint)
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image
from std_msgs.msg import String

from stage4.api_client import AeroVLAClient
from stage4.contracts import (PREFIX, action_target, atomic_json, enu,
                              enu_flu_quaternion, prompt, validate_task, wrap, yaw_xyzw)
from stage4.motion import Motion, InferenceGate
from stage4.evaluation import Evaluation


def seconds(stamp): return stamp.sec+stamp.nanosec*1e-9


def png(msg):
    if msg.encoding != 'rgb8' or msg.step != msg.width*3:
        raise ValueError('Camera input must be contiguous rgb8')
    image = PILImage.frombytes('RGB',(msg.width,msg.height),bytes(msg.data))
    output = BytesIO(); image.save(output,format='PNG')
    return output.getvalue()


class Control(Node):
    def __init__(self, directory=Path('/run/stage4')):
        super().__init__('stage4_control')
        self.directory = directory
        self.run_id=(directory/'run-id').read_text().strip()
        self.task = validate_task(json.loads((directory/'task.json').read_text()))
        self.config = self.task['control']; self.mode = 'idle'; self.reason = 'waiting for explicit task'
        self.p=self.v=self.q=self.vehicle=self.flags=self.origin=None
        self.odom_at=self.status_at=self.flags_at=self.clock_at=0.
        self.clock_last=None; self.reset=None; self.last_command=0.; self.stable=None
        self.motion=None; self.hold=None; self.yaw=0.; self.yaw_hold=0.; self.step=0
        self.future=None; self.gate=InferenceGate(); self.pool=ThreadPoolExecutor(max_workers=1)
        self.images={name:deque(maxlen=12) for name in ('front','down')}
        self.observations=deque(maxlen=12); self.sensor_at=0.; self.sensor_state={}
        self.started=None; self.reported=False; self.api=None; self.model_stop=False
        self.fixed=deque(); self.fixed_mode=False; self.trace=[]; self.last_record=0.
        self.depth=deque(maxlen=12); self.evaluation=None; self.evaluated_step=-1
        self.create_subscription(VehicleOdometry,'/fmu/out/vehicle_odometry',self.odom,qos_profile_sensor_data)
        self.create_subscription(VehicleStatus,'/fmu/out/vehicle_status_v4',self.status,qos_profile_sensor_data)
        self.create_subscription(FailsafeFlags,'/fmu/out/failsafe_flags',self.health,qos_profile_sensor_data)
        self.create_subscription(Odometry,PREFIX+'/observation/odom',self.observation,qos_profile_sensor_data)
        self.create_subscription(String,PREFIX+'/sensors',self.sensor,qos_profile_sensor_data)
        self.create_subscription(String,PREFIX+'/observation/depth',lambda msg:self.depth.append(json.loads(msg.data)),10)
        for name in self.images:
            self.create_subscription(Image,PREFIX+f'/camera/{name}/image_raw',
                lambda msg,n=name:self.images[n].append(msg),qos_profile_sensor_data)
        self.hb=self.create_publisher(OffboardControlMode,'/fmu/in/offboard_control_mode',10)
        self.sp=self.create_publisher(TrajectorySetpoint,'/fmu/in/trajectory_setpoint',10)
        suffix=f'_v{VehicleCommand.MESSAGE_VERSION}' if VehicleCommand.MESSAGE_VERSION else ''
        self.cmd=self.create_publisher(VehicleCommand,'/fmu/in/vehicle_command'+suffix,10)
        self.status_pub=self.create_publisher(String,PREFIX+'/status',10)
        self.create_timer(.02,self.tick,clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.create_timer(.2,self.snapshot,clock=Clock(clock_type=ClockType.STEADY_TIME))

    def odom(self,msg):
        if msg.pose_frame!=msg.POSE_FRAME_NED or msg.velocity_frame!=msg.VELOCITY_FRAME_NED: return
        if not all(math.isfinite(x) for x in [*msg.position,*msg.velocity,*msg.q]): return
        if self.reset is not None and self.reset!=msg.reset_counter and self.active(): self.land('estimator reset',True)
        self.reset=msg.reset_counter; self.p=list(map(float,msg.position)); self.v=list(map(float,msg.velocity))
        self.q=[*map(float,msg.q[1:]),float(msg.q[0])]; self.yaw=yaw_xyzw(self.q)
        self.odom_at=time.monotonic()

    def status(self,msg): self.vehicle=msg; self.status_at=time.monotonic()
    def health(self,msg): self.flags=msg; self.flags_at=time.monotonic()
    def observation(self,msg): self.observations.append((msg,time.monotonic()))
    def sensor(self,msg): self.sensor_state=json.loads(msg.data); self.sensor_at=time.monotonic()
    def now(self): return self.get_clock().now().nanoseconds*1e-9
    def armed(self): return self.vehicle is not None and self.vehicle.arming_state==self.vehicle.ARMING_STATE_ARMED
    def disarmed(self): return self.vehicle is not None and self.vehicle.arming_state==self.vehicle.ARMING_STATE_DISARMED
    def active(self): return self.mode not in ('idle','land','complete','failed')

    def healthy(self):
        wall=time.monotonic()
        fields=('angular_velocity_invalid','attitude_invalid','local_altitude_invalid','local_position_invalid','local_velocity_invalid')
        return (self.p is not None and self.vehicle is not None and self.flags is not None and
                wall-self.odom_at<.3 and wall-self.status_at<1.5 and wall-self.flags_at<1.5 and
                not any(getattr(self.flags,k) for k in fields))

    def cameras_ready(self):
        age=self.sensor_state.get('pair_age_s')
        return time.monotonic()-self.sensor_at<1.5 and age is not None and age<1.

    def command(self,code,p1=0.,p2=0.):
        msg=VehicleCommand(); msg.timestamp=int(self.now()*1e6); msg.command=code
        msg.param1=float(p1); msg.param2=float(p2); msg.target_system=1; msg.target_component=1
        msg.source_system=245; msg.source_component=1; msg.from_external=True; self.cmd.publish(msg)

    def start(self,request):
        if not self.healthy() or not self.cameras_ready() or not self.vehicle.pre_flight_checks_pass or not self.disarmed():
            raise RuntimeError('Start rejected: require healthy disarmed PX4 and synchronized cameras')
        self.fixed_mode=request.get('mode')=='fixed'
        if not self.fixed_mode: self.api=AeroVLAClient()
        self.origin=self.p[:]; self.hold=self.p[:]; self.yaw_hold=self.yaw
        self.started=time.monotonic(); self.phase_wall=self.started; self.mode='prestream'
        self.reason='explicit task'; self.failed=False
        # Exercise small and large yaw, horizontal and vertical motion, then return.
        self.fixed=deque([dict(fwd=1.,down=0.,yaw=0.),dict(fwd=1.,down=.5,yaw=.5),
                          dict(fwd=0.,down=-.5,yaw=-.5),dict(fwd=0.,down=0.,yaw=.1)])
        atomic_json(self.directory/'origin.json',dict(px4_origin_ned=self.origin,spawn_world_ned=self.task['spawn_ned_m']))

    def land(self,reason,failed):
        if self.mode in ('land','complete','failed'): return
        self.reason=reason; self.failed=failed; self.mode='land'; self.land_wall=time.monotonic(); self.land_sim=self.now()
        self.gate.cancel()
        if self.future: self.future.cancel()
        self.command(VehicleCommand.VEHICLE_CMD_NAV_LAND); self.last_command=time.monotonic()

    def move(self,target,yaw,mode):
        self.motion=Motion(self.p,target,self.yaw,yaw,self.now(),self.config)
        self.mode=mode; self.phase_wall=time.monotonic(); self.stable=None
        self.hold=list(target); self.yaw_hold=yaw

    def settled(self,done):
        okay=done and math.dist(self.p,self.hold)<=self.config['position_tolerance_m'] and \
             abs(wrap(self.yaw-self.yaw_hold))<=self.config['yaw_tolerance_rad'] and math.dist(self.v,[0,0,0])<=.2
        if not okay: self.stable=None; return False
        if self.stable is None: self.stable=self.now()
        return self.now()-self.stable>=self.config['stable_s']

    def next_observation(self):
        self.mode='observe'; self.phase_wall=time.monotonic(); self.after_sim=self.now()
        self.motion=None

    def pair(self):
        limit=self.config['max_pair_skew_s']
        for odom,wall in reversed(self.observations):
            t=seconds(odom.header.stamp)
            if t<self.after_sim or time.monotonic()-wall>1.: continue
            pair=[]
            for name in ('front','down'):
                if not self.images[name]: break
                image=min(self.images[name],key=lambda im:abs(seconds(im.header.stamp)-t))
                if abs(seconds(image.header.stamp)-t)>limit: break
                pair.append(image)
            depth=next((d for d in reversed(self.depth) if abs(d['observation_time_s']-t)<1e-6),None)
            if len(pair)==2 and depth is not None: return t,odom,pair,depth
        return None

    def inference(self):
        pair=self.pair()
        if pair is None: return
        stamp,odom,images,depth=pair
        p=odom.pose.pose.position; q=odom.pose.pose.orientation
        local=enu([p.x,p.y,p.z]); quat=enu_flu_quaternion([q.x,q.y,q.z,q.w])
        world=[s+x-o for s,x,o in zip(self.task['spawn_ned_m'],local,self.origin)]
        text=prompt(world,quat,self.task['target_ned_m'],self.task['object_description'])
        request_id=f'{self.run_id}:{self.step}'
        front,down=map(png,images)
        frame_dir=self.directory/'observations'/str(self.step); frame_dir.mkdir(parents=True)
        (frame_dir/'front.png').write_bytes(front); (frame_dir/'down.png').write_bytes(down)
        observation=dict(step=self.step,request_id=request_id,observation_time_s=stamp,prompt_preview=text,
                         estimated_world_ned=world,quaternion_xyzw=quat,depth_fractions=depth['fractions'],submitted=False)
        atomic_json(frame_dir/'input.json',observation)
        atomic_json(self.directory/'observation.json',observation)
        if self.evaluation is None:
            self.evaluation=Evaluation(self.task['target_ned_m'],self.config['success_distance_m'])
            self.evaluation.initialize(world)
        if self.step>0 and self.evaluated_step!=self.step:
            self.evaluated_step=self.step
            reason=self.evaluation.after_action(world,depth['fractions'])
            if reason:
                self.land(reason,True); return
        if self.step>=self.config['max_steps']:
            self.land('step limit',True); return
        self.gate.begin(request_id); self.infer_wall=time.monotonic()
        observation['submitted']=True
        atomic_json(frame_dir/'input.json',observation)
        atomic_json(self.directory/'observation.json',observation)
        self.future=self.pool.submit(self.api.infer,request_id,stamp,world,quat,
                                     self.task['target_ned_m'],self.task['instruction'],front,down)
        self.mode='infer'

    def execute(self,action):
        self.pending_target,self.pending_yaw=action_target(self.p,self.yaw,action)
        self.action_wall=time.monotonic()
        self.move(self.p,self.pending_yaw,'rotate')

    def finish(self,disarmed):
        if self.reported: return
        collision_path=self.directory/'collision.json'
        collision=json.loads(collision_path.read_text()) if collision_path.exists() else None
        flight_collision=bool(collision and collision.get('time_stamp',0)*1e-9<self.land_sim)
        if flight_collision:
            self.failed=True; self.reason='collision before landing: '+self.reason
        self.reported=True; self.mode='failed' if self.failed or not disarmed else 'complete'
        distance=None
        if self.p is not None and self.origin is not None:
            world=[s+x-o for s,x,o in zip(self.task['spawn_ned_m'],self.p,self.origin)]
            distance=math.dist(world,self.task['target_ned_m'])
        atomic_json(self.directory/'report.json',dict(mode=self.mode,reason=self.reason,
            chain_completed=disarmed and not self.failed,model_stop=self.model_stop,
            task_success=(self.model_stop and not self.failed and disarmed and bool(self.evaluation and self.evaluation.success)),
            evaluation=self.evaluation.snapshot() if self.evaluation else None,
            distance_at_stop_m=getattr(self,'stop_distance',None),distance_after_landing_m=distance,
            disarmed_confirmed=disarmed,steps=self.step,fixed_actions=self.fixed_mode,
            collision=collision,flight_collision=flight_collision,landing_started_sim_s=self.land_sim,
            wall_seconds=time.monotonic()-self.started if self.started else 0,
            task=self.task,reference_and_estimate_log='flight.jsonl',inference_log='inference.jsonl',
            scope='PX4 estimates drive control; target coordinates are supplied task knowledge; truth only evaluates'))

    def tick(self):
        wall=time.monotonic(); now=self.now()
        try:
            if self.clock_last is None or now!=self.clock_last: self.clock_at=wall
            if self.mode=='idle' and (self.directory/'start.json').exists():
                self.start(json.loads((self.directory/'start.json').read_text()))
            if self.active():
                if (self.directory/'land.request.json').exists(): self.land('operator requested landing',True)
                elif self.clock_last is not None and now<self.clock_last: self.land('clock reset',True)
                elif wall-self.clock_at>.5 or not self.healthy(): self.land('clock/state timeout',True)
                elif wall-self.sensor_at>self.config['observation_timeout_s'] or \
                     (self.sensor_state.get('pair_age_s') is not None and
                      self.sensor_state['pair_age_s']>self.config['observation_timeout_s']):
                    self.land('camera observation timeout',True)
                elif (self.directory/'collision.json').exists(): self.land('new collision',True)
                elif wall-self.started>self.config['mission_timeout_s']: self.land('mission timeout',True)
                elif self.mode not in ('prestream','takeoff') and self.vehicle.nav_state!=self.vehicle.NAVIGATION_STATE_OFFBOARD:
                    self.land('PX4 left Offboard',True)
            self.clock_last=now
            if self.mode=='prestream' and wall-self.started>=2:
                target=[p+s-b for p,s,b in zip(self.origin,self.task['start_ned_m'],self.task['spawn_ned_m'])]
                self.move(target,yaw_xyzw(self.task['start_quaternion_xyzw']),'takeoff')
            if self.mode=='takeoff':
                if wall-self.phase_wall>self.config['takeoff_timeout_s']: self.land('takeoff timeout',True)
                elif wall-self.last_command>1:
                    self.command(VehicleCommand.VEHICLE_CMD_DO_SET_MODE,1,6)
                    self.command(VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM,1); self.last_command=wall
            if self.mode in ('takeoff','rotate','move','return'):
                _,_,_,_,_,done=self.motion.sample(now)
                if self.mode in ('rotate','move') and wall-self.action_wall>self.config['action_timeout_s']:
                    self.land('action timeout',True)
                elif self.mode=='return' and wall-self.phase_wall>self.config['action_timeout_s']:
                    self.land('return timeout',True)
                elif self.settled(done) and (self.mode!='takeoff' or self.armed()):
                    if self.mode=='rotate': self.move(self.pending_target,self.pending_yaw,'move')
                    elif self.mode=='return': self.land('fixed actions completed',False)
                    else: self.next_observation()
            if self.mode=='observe':
                if self.fixed_mode and self.step>=self.config['max_steps']: self.land('step limit',True)
                elif wall-self.phase_wall>self.config['observation_timeout_s']: self.land('observation timeout',True)
                elif self.fixed_mode:
                    if self.fixed: self.execute(self.fixed.popleft()); self.step+=1
                    else:
                        target=[p+s-b for p,s,b in zip(self.origin,self.task['start_ned_m'],self.task['spawn_ned_m'])]
                        self.move(target,yaw_xyzw(self.task['start_quaternion_xyzw']),'return')
                else: self.inference()
            if self.mode=='infer':
                if wall-self.infer_wall>self.api.timeout+1: self.land('API timeout',True)
                elif self.future.done():
                    response=self.future.result()
                    if self.gate.accept(response['request_id']):
                        with (self.directory/'inference.jsonl').open('a') as out:
                            out.write(json.dumps(dict(step=self.step,**response))+'\n')
                        self.step+=1
                        if response['stop']:
                            self.model_stop=True
                            world=json.loads((self.directory/'observation.json').read_text())['estimated_world_ned']
                            self.stop_distance=math.dist(world,self.task['target_ned_m'])
                            reason=self.evaluation.stop(world)
                            self.land(reason,not self.evaluation.success)
                        else: self.execute(response['action'])
            if self.mode=='land':
                if self.vehicle and wall-self.status_at<1.5 and self.disarmed(): self.finish(True)
                elif wall-self.land_wall>60: self.finish(False)
                elif wall-self.last_command>2:
                    self.command(VehicleCommand.VEHICLE_CMD_NAV_LAND); self.last_command=wall
            if self.active(): self.publish_reference(now)
        except Exception as exc:
            self.get_logger().error(str(exc))
            self.land(f'{type(exc).__name__}: {exc}',True)

    def publish_reference(self,now):
        if self.motion and self.mode in ('takeoff','rotate','move','return'):
            p,v,a,yaw,rate,_=self.motion.sample(now)
        else: p,v,a,yaw,rate=self.hold,[0.]*3,[0.]*3,self.yaw_hold,0.
        heartbeat=OffboardControlMode(); heartbeat.timestamp=int(now*1e6); heartbeat.position=True
        self.hb.publish(heartbeat)
        msg=TrajectorySetpoint(); msg.timestamp=int(now*1e6); msg.position=list(map(float,p))
        msg.velocity=list(map(float,v)); msg.acceleration=list(map(float,a)); msg.yaw=float(yaw); msg.yawspeed=float(rate)
        self.sp.publish(msg)
        if time.monotonic()-self.last_record>.1:
            self.last_record=time.monotonic()
            with (self.directory/'flight.jsonl').open('a') as out:
                out.write(json.dumps(dict(sim_s=now,wall_elapsed_s=self.last_record-self.started,
                    mode=self.mode,position_ned=self.p,velocity_ned=self.v,yaw_ned=self.yaw,
                    reference_ned=p,reference_yaw_ned=yaw))+'\n')

    def snapshot(self):
        state=dict(mode=self.mode,reason=self.reason,healthy=bool(self.healthy()),
                   cameras_ready=bool(self.cameras_ready()),armed=bool(self.armed()),step=self.step,
                   sim_s=self.now(),position_ned=self.p,velocity_ned=self.v,yaw_ned=self.yaw,
                   wall_time=time.time(),clock_age_s=time.monotonic()-self.clock_at,
                   landing_started_sim_s=getattr(self,'land_sim',None),
                   wall_elapsed_s=time.monotonic()-self.started if self.started else 0.,
                   api_configured=bool(__import__('os').environ.get('AEROVLA_API_URL')))
        state['evaluation']=self.evaluation.snapshot() if self.evaluation else None
        atomic_json(self.directory/'control.json',state)
        self.status_pub.publish(String(data=json.dumps(state)))


def main():
    rclpy.init(); node=Control()
    try: rclpy.spin(node)
    finally:
        if node.active(): node.land('control shutdown',True)
        node.pool.shutdown(wait=False,cancel_futures=True); node.destroy_node(); rclpy.try_shutdown()


if __name__=='__main__': main()
