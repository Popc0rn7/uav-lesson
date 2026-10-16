#!/usr/bin/env python3
"""PC：复用上游真实 A* 回归，生成无运动的板端预算/计时探针。"""
import argparse
import yaml
from build import ROOT, OUTPUT, build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=float, default=.1,
                        help='仅空图诊断期限；不修改任何飞行配置，默认 0.1 秒')
    args = parser.parse_args()
    if not 0 < args.budget <= 5:
        parser.error('budget 必须在 (0,5] 秒')
    source = (ROOT/'submodules/SUPER/super_planner/test/astar_clipped_goal_test.cpp').read_text()
    replacements = {
        '#include <iostream>':'#include <iostream>\n#include <chrono>',
        'const auto result = astar.':'auto before=std::chrono::steady_clock::now();\n        const auto result = astar.',
        'path, 5.);':f'path, {args.budget});\n        std::cout << "WALL_SECONDS " << name << " " << std::chrono::duration<double>(std::chrono::steady_clock::now()-before).count() << std::endl;',
        'check("near-before", {0, 5, 2}, super_utils::REACH_GOAL);':
            'check("near-before", {0, 5, 2}, super_utils::REACH_GOAL);\n    check("forest1-first-goal", {-3.3,11.5,1.9}, super_utils::REACH_GOAL);',
    }
    for original, replacement in replacements.items():
        if source.count(original) != 1:
            raise RuntimeError('上游测试已变化，需复核诊断插入位置：'+original)
        source = source.replace(original, replacement)
    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT/'astar_budget.cpp'
    path.write_text(source)
    config = yaml.safe_load((ROOT/'stage3/super/airsim/planner.base.yaml').read_text())
    for section in ('ros_callback','visualization','raycasting'):
        config['rog_map'][section]['enable'] = False
    config['rog_map']['fix_map_origin'] = [0,0,2]
    (OUTPUT/'astar-empty.yaml').write_text(yaml.safe_dump(config))
    build(path,'astar_budget')
    print('仅生成探针；板端使用独立域 191、无 PX4/Agent 的环境运行。')


if __name__ == '__main__':
    main()
