"""Read the current AeroVLA workspace without importing its inference stack."""
import argparse
import json
from pathlib import Path

from stage4.contracts import DEFAULTS, atomic_json, validate_task


def prepare(root, index=0, ground_z=0.):
    root = Path(root).expanduser().resolve()
    split = json.loads((root/'data/uav_dataset/seen_valset_splits/Carla_Town05.json').read_text())
    paths = sorted({item['json'] for item in split})
    if not 0 <= index < len(paths):
        raise ValueError(f'task-index must be 0–{len(paths)-1}')
    relative = Path(paths[index])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Invalid dataset path')
    source = root/'dataset_raw'/relative
    merged = json.loads(source.read_text())
    mark = json.loads(source.with_name('mark.json').read_text())
    areas = json.loads((root/'data/meta/map_spawnarea_info.json').read_text())['Carla_Town05']
    target = mark['target']['position']
    area = min((a for a in areas if len(a) >= 18),
               key=lambda a: sum((x-y)**2 for x,y in zip(target, [a[0]+1,a[1]+1,a[2]+.5])))
    start = merged['trajectory_raw_detailed'][0]
    instruction = merged['conversations'][0]['value']
    try:
        description = instruction.split('degrees from you.', 1)[1].split(' Please control', 1)[0].strip()
    except IndexError as exc:
        raise ValueError('Instruction does not match the original AeroVLA format') from exc
    return validate_task(dict(name=f'Town05 task {index}', task_index=index,
        source=dict(checkout=str(root), trajectory=str(relative)), instruction=instruction,
        object_description=description, start_ned_m=start['position'],
        start_quaternion_xyzw=start['orientation'], spawn_ned_m=[*start['position'][:2], ground_z],
        target_ned_m=area[9:12], object=dict(asset=area[16], position=area[9:12],
            quaternion_xyzw=[*area[13:16],area[12]], scale=area[17]), control=dict(DEFAULTS)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[2]/'AeroVLA')
    parser.add_argument('--task-index', type=int, default=0)
    parser.add_argument('--ground-z', type=float, default=0., help='Town05 ground spawn world NED Z, metres')
    parser.add_argument('--output', type=Path, default=Path('artifacts/stage4/task.json'))
    args = parser.parse_args()
    task = prepare(args.source, args.task_index, args.ground_z)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f'Refusing to overwrite {args.output}; select a new --output')
    atomic_json(args.output, task)
    print(args.output)


if __name__ == '__main__':
    main()
