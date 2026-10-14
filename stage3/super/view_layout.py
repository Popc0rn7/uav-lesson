#!/usr/bin/env python3
"""PC：通过 XWayland/EWMH 摆放课程三窗口，不改变仿真状态。"""
import ctypes as C
import os
import re
import shutil
import subprocess
import time


class ClientMessage(C.Structure):
    _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int),
                ('display', C.c_void_p), ('window', C.c_ulong),
                ('message_type', C.c_ulong), ('format', C.c_int), ('data', C.c_long * 5)]


class Event(C.Union):
    _fields_ = [('client', ClientMessage), ('padding', C.c_long * 24)]


def prop(*args):
    return subprocess.check_output(['xprop', *args], text=True, stderr=subprocess.DEVNULL)


def apply_layout(timeout=15):
    if not shutil.which('xprop') or not os.environ.get('DISPLAY'):
        print('窗口布局未应用：需要 DISPLAY 和 PC xprop。', flush=True)
        return False
    lib = C.CDLL('libX11.so.6')
    lib.XOpenDisplay.argtypes = [C.c_char_p]; lib.XOpenDisplay.restype = C.c_void_p
    lib.XDefaultRootWindow.argtypes = [C.c_void_p]; lib.XDefaultRootWindow.restype = C.c_ulong
    lib.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]; lib.XInternAtom.restype = C.c_ulong
    lib.XSendEvent.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_long, C.POINTER(Event)]
    lib.XFlush.argtypes = [C.c_void_p]
    lib.XCloseDisplay.argtypes = [C.c_void_p]
    display = lib.XOpenDisplay(None)
    if not display:
        print('窗口布局未应用：无法连接桌面 XWayland/X11。', flush=True)
        return False
    root = lib.XDefaultRootWindow(display)

    def send(window, message, values):
        event = Event()
        event.client = ClientMessage(33, 0, 1, display, window,
                                     lib.XInternAtom(display, message.encode(), 0),
                                     32, (C.c_long * 5)(*values))
        lib.XSendEvent(display, root, 0, (1 << 20) | (1 << 19), C.byref(event))
        lib.XFlush(display)

    try:
        workarea = prop('-root', '_NET_WORKAREA').split('=', 1)[1]
        x, y, width, height = map(int, re.findall(r'-?\d+', workarea)[:4])
        gap = 12
        left = (width - 3 * gap) // 2
        half = (height - 3 * gap) // 2
        boxes = {
            'super_gazebo_cloud.rviz': (x + gap, y + gap, left, half),
            'super_gazebo_map.rviz': (x + gap, y + 2 * gap + half, left, height - 3 * gap - half),
            'Gazebo Sim': (x + 2 * gap + left, y + gap, width - 3 * gap - left, height - 2 * gap),
        }
        pending = dict(boxes)
        deadline = time.monotonic() + timeout
        while pending and time.monotonic() < deadline:
            ids = re.findall(r'0x[0-9a-fA-F]+', prop('-root', '_NET_CLIENT_LIST'))
            for token in ids:
                try:
                    title = prop('-id', token, '_NET_WM_NAME')
                    key = next((key for key in pending if key in title), None)
                    if key is None:
                        continue
                    window = int(token, 16)
                    extents = prop('-id', token, '_NET_FRAME_EXTENTS')
                    frame = list(map(int, re.findall(r'\d+', extents.split('=', 1)[-1])))
                    l, r, t, b = frame[:4] if len(frame) >= 4 else (0, 0, 0, 0)
                    bx, by, bw, bh = pending[key]
                    atoms = [lib.XInternAtom(display, name, 0) for name in
                             (b'_NET_WM_STATE_MAXIMIZED_VERT', b'_NET_WM_STATE_MAXIMIZED_HORZ')]
                    send(window, '_NET_WM_STATE', [0, *atoms, 2, 0])
                    send(window, '_NET_MOVERESIZE_WINDOW', [(2 << 12) | (15 << 8), bx, by,
                                                          max(1, bw-l-r), max(1, bh-t-b)])
                    del pending[key]
                except subprocess.CalledProcessError:
                    continue  # A window may disappear while the desktop list is read.
            if pending:
                time.sleep(.25)
        if pending:
            print('窗口布局未全部应用，未找到：' + ', '.join(pending), flush=True)
            return False
        print('窗口布局：左上点云 RViz，左下地图 RViz，右侧 Gazebo。', flush=True)
        return True
    except (subprocess.CalledProcessError, ValueError, IndexError) as exc:
        print(f'窗口布局未应用：{exc}', flush=True)
        return False
    finally:
        lib.XCloseDisplay(display)


if __name__ == '__main__':
    raise SystemExit(0 if apply_layout() else 1)
