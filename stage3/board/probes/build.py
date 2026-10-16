#!/usr/bin/env python3
"""PC：复用已验证目标构建命令，编译无运动的 ROS 类型/时钟诊断探针。"""
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / 'artifacts/robopi-stage3/build/super_planner'
OUTPUT = ROOT / 'artifacts/robopi-stage3/probes'


def build(source, name):
    OUTPUT.mkdir(exist_ok=True)
    entries = json.loads((BUILD/'compile_commands.json').read_text())
    entry = next(e for e in entries if e['file'].endswith('fsm_node_ros2.cpp'))
    command = shlex.split(entry['command'])
    object_file=OUTPUT/(name+'.o')
    executable=OUTPUT/name
    command[command.index('-o')+1] = str(object_file)
    command[command.index('-c')+1] = str(source)
    subprocess.run(command, cwd=BUILD, check=True)
    line = subprocess.check_output(['ninja','-t','commands','fsm_node'], cwd=BUILD, text=True).splitlines()[-1]
    tokens = shlex.split(line)
    command = tokens[2:tokens.index('&&',2)]
    command[command.index('-o')+1] = str(executable)
    command = [str(object_file) if token=='CMakeFiles/fsm_node.dir/Apps/fsm_node_ros2.cpp.o' else token
               for token in command]
    index = command.index('-Xlinker')
    del command[index:index+2]
    subprocess.run(command, cwd=BUILD, check=True)
    print(executable)
    return executable


if __name__ == '__main__':
    build(Path(__file__).with_name('ros_topics.cpp'),'ros_topics')
