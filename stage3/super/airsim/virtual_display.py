"""PC：独立且可核验身份的 Xvfb；不更改用户桌面或 GPU 驱动。"""
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import time


def identity(pid):
    try:
        root=Path('/proc')/str(pid)
        fields=(root/'stat').read_text().rsplit(')',1)[1].split()
        if fields[0]=='Z':return None
        return dict(pid=pid,ticks=fields[19],exe=str((root/'exe').resolve()),
                    argv=(root/'cmdline').read_bytes().hex())
    except OSError:return None


def start(directory):
    binary=shutil.which('Xvfb')
    if not binary:raise RuntimeError('无显示测试需要已安装 Xvfb；不会自动安装')
    read_fd,write_fd=os.pipe()
    process=None
    try:
        with (directory/'xvfb.log').open('wb') as log:
            process=subprocess.Popen([binary,'-displayfd',str(write_fd),'-screen','0','640x480x24','-nolisten','tcp'],
                                     pass_fds=(write_fd,),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        os.close(write_fd);write_fd=None
        if not select.select([read_fd],[],[],10)[0]:raise RuntimeError('Xvfb 显示号等待超时')
        number=os.read(read_fd,80).decode().strip()
        record=identity(process.pid)
        if not number.isdigit() or process.poll() is not None or not record:
            raise RuntimeError('Xvfb 未就绪，检查 xvfb.log')
        return dict(display=':'+number,process=record)
    except BaseException:
        if process and process.poll() is None:process.terminate();process.wait(timeout=5)
        raise
    finally:
        os.close(read_fd)
        if write_fd is not None:os.close(write_fd)


def alive(record):
    return bool(record and identity(record['process']['pid'])==record['process'])


def stop(record):
    if alive(record):
        os.kill(record['process']['pid'],signal.SIGTERM)
        deadline=time.monotonic()+5
        while alive(record) and time.monotonic()<deadline:
            time.sleep(.05)
        if alive(record):
            raise RuntimeError('本次 Xvfb 仍未退出，保留状态供诊断')
