"""PC：拉取模型到 artifacts/models；已有缓存不覆盖。"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True, help='发布方确认的固定版本')
    args = parser.parse_args()
    save_dir = ROOT / 'artifacts/models/Qwen3.6-35B-A3B'
    if save_dir.exists() or save_dir.is_symlink():
        raise FileExistsError(f'已有模型或缓存链接，直接复用：{save_dir}')
    from modelscope import snapshot_download
    model_dir = snapshot_download('Houmo/xh2_qwen3.6_35b-a3b_256k',
                                  revision=args.revision, local_dir=str(save_dir))
    print(model_dir)


if __name__ == '__main__':
    main()
