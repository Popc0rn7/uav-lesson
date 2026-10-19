"""本轮 Shipping 场景的进程身份、启动和回收；不接管外部进程。"""
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time


def paths(config):
    root = Path(config['package_dir']).expanduser().resolve()
    project = config.get('project_name', 'demo')
    binary = Path(config.get('scene_binary') or root/project/'Binaries/Linux'/(project+'-Linux-Shipping'))
    return root, binary, root/project/'Config/AirSim/settings.json'


def validate(config):
    root, binary, settings = paths(config)
    project = config.get('project_name', 'demo')
    required = [binary, settings, root/project/'Content/Paks'/(project+'-LinuxNoEditor.pak')]
    required += [root/project/'Saved/SaveGames'/f'{name}Convoy3Route01.sav'
                 for name in ('Pickup', 'Armored', 'Van')]
    for path in required:
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError(f'打包场景交付文件缺失或为空：{path}')
    if not os.access(binary, os.X_OK):
        raise RuntimeError(f'Shipping程序没有执行权限：{binary}')
    return required


def start_ticks(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def alive(info):
    if not info:
        return False
    try:
        pid = info['pid']
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return (stat[0] != 'Z' and stat[19] == info['start_ticks']
                and Path(f'/proc/{pid}/exe').resolve() == Path(info['binary'])
                and info['settings_arg'].encode() in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0'))
    except (OSError, KeyError):
        return False


def launch(config, directory):
    required = validate(config)
    if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        raise RuntimeError('当前窗口模式需要图形桌面环境；请在桌面终端执行runtime up（DISPLAY未设置）')
    root, binary, settings = paths(config)
    args = [str(binary), 'demo', f'-UserDir={root}/{config.get("project_name", "demo")}/', f'-settings={settings}',
            *config.get('scene_args', [])]
    # 保存交付身份；pak是静态大文件，记录大小/时间，二进制及配置/路线记录hash。
    identity = {str(p.relative_to(root)): dict(size=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns,
                **({'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} if p.suffix != '.pak' else {}))
                for p in required}
    with (directory/'scene.log').open('ab') as log:
        process = subprocess.Popen(args, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, stdin=subprocess.DEVNULL)
    try:
        ticks = start_ticks(process.pid)
    except OSError:
        process.wait()
        raise RuntimeError(f'Shipping启动即退出，见{directory}/scene.log') from None
    return dict(pid=process.pid, start_ticks=ticks, binary=str(binary), settings_arg=f'-settings={settings}',
                argv=args, identity=identity, log=str(directory/'scene.log'), managed=True)


def stop(info, timeout=10):
    if not info or not alive(info):
        return
    os.kill(info['pid'], signal.SIGTERM)
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if not alive(info):
            return
        time.sleep(.1)
    if alive(info):
        os.kill(info['pid'], signal.SIGKILL)
        deadline = time.monotonic()+3
        while alive(info) and time.monotonic() < deadline:
            time.sleep(.1)
    if alive(info):
        raise RuntimeError('本轮场景仍未退出，保留stopping状态供后续回收')
