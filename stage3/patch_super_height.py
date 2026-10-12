#!/usr/bin/env python3
"""PC：仅修改本地 SUPER 工作副本，为搜索与走廊增加一致的中心高度限制。"""
from pathlib import Path


def patch(root):
    root = Path(root)
    helper = root / 'rog_map/include/rog_map/stage3_height.h'
    helper_content='''#pragma once
#include <cstdlib>
#include <limits>
#include <algorithm>
namespace stage3_height {
inline double low() { const char *p=std::getenv("SUPER_CENTER_Z_MIN"); return p ? std::atof(p) : -std::numeric_limits<double>::infinity(); }
inline double high() { const char *p=std::getenv("SUPER_CENTER_Z_MAX"); return p ? std::atof(p) : std::numeric_limits<double>::infinity(); }
inline bool allowed(double z) { return z >= low() && z <= high(); }
inline double cell_height(double z, double resolution) {
  if (z < low() && z + resolution*.5 > low()) return std::min(low()+.01,z+resolution*.5-.001);
  if (z > high() && z - resolution*.5 < high()) return std::max(high()-.01,z-resolution*.5+.001);
  return z;
}
template<class V> void clip(V &lo, V &hi) { lo.z()=std::max(lo.z(),low()); hi.z()=std::min(hi.z(),high()); }
}
'''
    if not helper.exists() or helper.read_text()!=helper_content:
        helper.write_text(helper_content)
    forward=root/'super_planner/include/super_core/stage3_height.h'
    forward_content='#pragma once\n#include <rog_map/stage3_height.h>\n'
    if not forward.exists() or forward.read_text()!=forward_content:
        forward.write_text(forward_content)
    nearest=root/'rog_map/src/rog_map/rog_map.cpp'
    content=nearest.read_text()
    if 'stage3_height::cell_height' not in content:
        content='#include <rog_map/stage3_height.h>\n'+content
        old='globalIndexToPos(q_id, q_pos);'
        assert content.count(old)==2
        content=content.replace(old,old+'\n        q_pos.z()=stage3_height::cell_height(q_pos.z(),cfg_.resolution);\n        if (!stage3_height::allowed(q_pos.z())) continue;')
        nearest.write_text(content)
    astar = root / 'super_planner/src/super_core/astar.cpp'
    corridor = root / 'super_planner/src/super_core/corridor_generator.cpp'
    for path in (astar, corridor):
        content = path.read_text()
        if '#include <super_core/stage3_height.h>' in content:
            continue
        content = '#include <super_core/stage3_height.h>\n' + content
        if path == astar:
            old = 'globalIndexToPos(neighborIdx, neighborPos);'
            assert content.count(old) == 2
            content = content.replace(old, old + '\n                        if (!stage3_height::allowed(neighborPos.z())) continue;')
        else:
            old = 'box_max.z() -= robot_r_;'
            assert content.count(old) == 2
            content = content.replace(old, old + '\n        stage3_height::clip(box_min, box_max);\n        if (box_min.z() >= box_max.z()) return false;')
            old = 'box_max += Vec3f(dis, dis, dis);'
            assert content.count(old) == 1
            content = content.replace(old, old + '\n        stage3_height::clip(box_min, box_max);\n        if (box_min.z() >= box_max.z()) return false;')
        path.write_text(content)
    content=astar.read_text()
    if 'stage3_height::cell_height' not in content:
        old='''            throw std::runtime_error(" -- [A*] Map type not defined.");
        }
    }

    bool Astar::insideLocalMap'''
        assert content.count(old)==1
        content=content.replace(old,'''            throw std::runtime_error(" -- [A*] Map type not defined.");
        }
        pos.z()=stage3_height::cell_height(pos.z(),md_.resolution);
    }

    bool Astar::insideLocalMap''')
        astar.write_text(content)
    fsm=root/'super_planner/src/super_core/fsm.cpp'
    content=fsm.read_text()
    if 'stage3_height::allowed' not in content:
        content='#include <super_core/stage3_height.h>\n'+content
        old='planner_ptr_->getMap()->getNearestInfCellNot(GridType::OCCUPIED, gi_.goal_p, gi_.goal_p, 3.0);'
        assert content.count(old)==1
        content=content.replace(old,'''if (!std::isfinite(stage3_height::low()) || planner_ptr_->getMap()->getInfGridType(gi_.goal_p)==GridType::OCCUPIED) {
            Vec3f shifted;
            if (!planner_ptr_->getMap()->getNearestInfCellNot(GridType::OCCUPIED, gi_.goal_p, shifted, 3.0) || !stage3_height::allowed(shifted.z())) return;
            gi_.goal_p=shifted;
        }''')
        old='if (planner_ptr_->getMap()->getNearestInfCellNot(GridType::OCCUPIED, click_point, gi_.goal_p, 3.0)) {'
        assert content.count(old)==1
        content=content.replace(old,'''const bool preserve = std::isfinite(stage3_height::low()) && planner_ptr_->getMap()->getInfGridType(click_point)!=GridType::OCCUPIED;
        if (preserve) gi_.goal_p=click_point;
        if (preserve || planner_ptr_->getMap()->getNearestInfCellNot(GridType::OCCUPIED, click_point, gi_.goal_p, 3.0)) {
            if (!stage3_height::allowed(gi_.goal_p.z())) return;''')
        fsm.write_text(content)


if __name__ == '__main__':
    patch(Path(__file__).resolve().parents[1] / 'thirdparty/super_gazebo_ws/src/SUPER')
