"""PC：从交接配置生成与当前任务一致的 SUPER 参数。"""
import sys
from pathlib import Path
import yaml
from task_config import load_task


TIMING_PROFILES = ('baseline', 'robopi-relaxed', 'robopi-forward-200ms')


def generate(task_path, output, timing_profile='baseline'):
    if timing_profile not in TIMING_PROFILES:
        raise ValueError('未知 planner_timing：'+str(timing_profile))
    task = load_task(task_path)
    config = yaml.safe_load(Path(__file__).with_name('planner.base.yaml').read_text())
    config['traj_opt']['boundary'].update(max_vel=task['speed_m_s'], max_acc=task['max_acc_m_s2'])
    config['rog_map'].update(virtual_ground_height=task['virtual_ground_height_m'],
                             virtual_ceil_height=task['virtual_ceil_height_m'])
    config['rog_map']['ros_callback']['odom_timeout'] = .5
    if timing_profile == 'robopi-relaxed':
        # Preserve the 0.1 simulation-second trajectory lookahead. The native
        # guard also checks elapsed simulation time, never only this wall cap.
        config['super_planner']['replan_wall_limit'] = .35
    elif timing_profile == 'robopi-forward-200ms':
        # Increase the handover lookahead with the simulation-time budget;
        # native code still rejects a plan taking more than 90% of this window.
        config['super_planner'].update(replan_forward_dt=.2, replan_wall_limit=.35)
    Path(output).write_text(yaml.safe_dump(config, sort_keys=False))


if __name__ == '__main__':
    generate(*sys.argv[1:])
