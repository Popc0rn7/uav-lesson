#!/usr/bin/env python3
"""Gazebo Docker：平地定点悬停时测量机体回波对应的地面遮挡投影。真值仅用于评测。"""
import argparse
import json
import math
import os
import threading
import time
from pathlib import Path
import struct
from gz.transport13 import Node
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.msgs10.pointcloud_packed_pb2 import PointCloudPacked


def rotation(q):
    x,y,z,w=q.x,q.y,q.z,q.w
    return [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sensor-z',type=float,required=True)
    parser.add_argument('--output',default='/tmp/lidar-occlusion.json')
    args=parser.parse_args()
    lock=threading.Lock();state={'pose':None,'frames':[],'error':None,'stable_since':None}
    def pose(msg):
        for p in msg.pose:
            if p.name=='x500_experiment_0':
                r=rotation(p.orientation)
                base=[v+.24*r[i][2] for i,v in enumerate((p.position.x,p.position.y,p.position.z))]
                now=time.monotonic()
                stamp=msg.header.stamp.sec+msg.header.stamp.nsec*1e-9
                with lock:
                    okay=1.85<=base[2]<=2.05 and r[2][2]>math.cos(math.radians(10))
                    state['stable_since']=(state['stable_since'] or now) if okay else None
                    state['pose']=(now,base,r,stamp)
    def cloud(msg):
        with lock:current=state['pose'];done=len(state['frames'])>=5;stable=state['stable_since']
        if stable is None or time.monotonic()-stable<3:return
        if done or current is None or time.monotonic()-current[0]>.2:return
        _,base,r,_=current
        if not 1.3<=base[2]<=2.2 or r[2][2]<math.cos(math.radians(10)):return
        # This benchmark is specific to the regular GENERAL_360 grid.
        if msg.width*msg.height!=1200*594:
            with lock:state['error']='Requires GENERAL_360 1200 x 594 scan'
            return
        offsets={f.name:f.offset for f in msg.field}
        if not all(k in offsets for k in ('x','y','z')):return
        origin=[base[i]+r[i][2]*args.sensor_z for i in range(3)]
        body_rays=0;area=0.;max_radius=0.
        data=msg.data
        point_step,row_step=msg.point_step,msg.row_step
        for row in range(msg.height):
            for col in range(msg.width):
                start=row*row_step+col*point_step
                p=[struct.unpack_from('<f',data,start+offsets[k])[0] for k in ('x','y','z')]
                norm2=sum(v*v for v in p)
                if not 1e-10<norm2<.65**2 or not all(math.isfinite(v) for v in p):continue
                norm=math.sqrt(norm2)
                direction=[sum(r[i][j]*p[j] for j in range(3))/norm for i in range(3)]
                if direction[2]>=-1e-4:continue
                distance=-origin[2]/direction[2]
                radius=math.hypot(origin[0]+direction[0]*distance-base[0],origin[1]+direction[1]*distance-base[1])
                if radius>=2:continue
                body_rays+=1;max_radius=max(max_radius,radius)
                # Flat-floor projection Jacobian of the regular sensor angle grid.
                area+=origin[2]**2*math.sqrt(max(0,1-(p[2]/norm)**2))/(-direction[2])**3*(2*math.pi/1200)*math.radians(178)/593
        result={'height_m':float(base[2]),'body_rays_in_2m_disk':body_rays,
                'occluded_floor_area_m2':area,'max_occluded_radius_m':max_radius}
        with lock:state['frames'].append(result)
    node=Node();node.subscribe(Pose_V,'/world/corridor/dynamic_pose/info',pose)
    node.subscribe(PointCloudPacked,'/mid360s/scan/points',cloud)
    end=time.monotonic()+120
    while time.monotonic()<end:
        with lock:done=len(state['frames'])>=5 or state['error'] is not None
        if done:break
        time.sleep(.05)
    node.unsubscribe('/mid360s/scan/points')
    node.unsubscribe('/world/corridor/dynamic_pose/info')
    with lock:frames=list(state['frames']);error=state['error']
    if error or len(frames)<5:raise SystemExit(error or f'Need stable hover: sampled {len(frames)} / 5 frames')
    report={'sensor_z_m':args.sensor_z,'frames':len(frames),'disk_radius_m':2,
            'method':'Approximate ground projection of near-body raw returns; flat floor, hover, GENERAL_360 only',
            **{k:sum(f[k] for f in frames)/len(frames) for k in frames[0]}}
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2),flush=True)
    # Gazebo transport13 Python callback teardown aborts during interpreter exit
    # on this image. This bounded diagnostic has flushed its only output and
    # unsubscribed; bypass interpreter teardown without affecting the server.
    os._exit(0)


if __name__=='__main__':main()
