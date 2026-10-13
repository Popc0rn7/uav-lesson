#!/usr/bin/env python3
"""Gazebo Docker：仅向验收提供真值、接触和实时率，不参与规划。"""
import json
import os
import threading
import time
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from gz.transport13 import Node
from gz.msgs10.contacts_pb2 import Contacts
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.msgs10.world_stats_pb2 import WorldStatistics
from gz.msgs10.pointcloud_packed_pb2 import PointCloudPacked

world = os.environ.get('PX4_GZ_WORLD', 'default')
lock = threading.Lock()
state = dict(world=world, pose=None, pose_at=0., pose_sim_time=0., contacts=[], scans=0, points=0,
             scan_at=0., max_scan_gap_s=0., sim_time=0., real_time_factor=0., started=time.monotonic())


def pose(msg):
    for p in msg.pose:
        if p.name == 'x500_experiment_0':
            with lock:
                q=p.orientation
                # Included x500_base places base_link 0.24 m above the model origin.
                base=[p.position.x+.24*2*(q.x*q.z+q.w*q.y),
                      p.position.y+.24*2*(q.y*q.z-q.w*q.x),
                      p.position.z+.24*(1-2*(q.x*q.x+q.y*q.y))]
                state.update(pose=base,pose_at=time.monotonic(),pose_sim_time=msg.header.stamp.sec+msg.header.stamp.nsec*1e-9)


def contacts(msg):
    with lock:
        for c in msg.contact:
            a,b = c.collision1.name,c.collision2.name
            if 'x500' in a or 'x500' in b:
                state['contacts'].append(dict(collision1=a,collision2=b,sim_time=state['sim_time']))
        state['contacts'] = state['contacts'][-200:]


def stats(msg):
    with lock:
        state.update(sim_time=msg.sim_time.sec+msg.sim_time.nsec*1e-9,real_time_factor=msg.real_time_factor)


def scan(msg):
    now=time.monotonic()
    with lock:
        if state['scan_at']:
            state['max_scan_gap_s']=max(state['max_scan_gap_s'],now-state['scan_at'])
        state.update(scans=state['scans']+1,points=msg.width*msg.height,scan_at=now)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/state':
            self.send_error(404);return
        with lock:
            payload=json.dumps(state).encode()
        self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)

    def log_message(self,*args):
        pass


if __name__ == '__main__':
    node=Node()
    node.subscribe(Pose_V,f'/world/{world}/dynamic_pose/info',pose)
    node.subscribe(WorldStatistics,f'/world/{world}/stats',stats)
    node.subscribe(PointCloudPacked,'/mid360s/scan/points',scan)
    layout=json.loads(Path('/lesson-stage3/corridor_layout.json').read_text())
    names=['wall_left','wall_right']+[f'pole_{i}' for i in range(len(layout['poles']))]+[f'shrub_{i}' for i in range(len(layout['shrubs']))]
    if os.environ.get('STAGE3_WALL_LANDMARKS')=='true':
        landmarks=json.loads(Path('/lesson-stage3/lio_landmarks.json').read_text())
        names.extend(f'lio_landmark_{i}' for i in range(len(landmarks['centers'])))
    for name in names:
        # Harmonic Contact system publishes its scoped topic (ignores sensor/topic).
        node.subscribe(Contacts,f'/world/{world}/model/{name}/link/link/sensor/contacts/contact',contacts)
    ThreadingHTTPServer(('127.0.0.1',8096),Handler).serve_forever()
