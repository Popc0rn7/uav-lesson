"""在本机 x86_64 真正执行 guard，验证两个分支和调用参数。"""
import ctypes
import mmap
from pathlib import Path
import sys
import struct
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare import GUARD, LOCKSTEP_VA, SITL_HIL_CALLS, patch


class GuardTest(unittest.TestCase):
    def test_sitl_skips_only_legacy_hil_mode_send_calls(self):
        binary = Path(__file__).resolve().parents[3]/'submodules/drone-race/ADRL/ADRL/Binaries/Linux/ADRL'
        if not binary.exists():
            self.skipTest('需要教师准备的已知 ADRL ELF')
        original = binary.read_bytes()
        modified = patch(original, disable_lockstep=True)
        calls = []
        callback = ctypes.CFUNCTYPE(None)(lambda: calls.append('sendCommand'))
        target = ctypes.cast(callback, ctypes.c_void_p).value
        for address in SITL_HIL_CALLS:
            site = address-0x200000
            before = original[site:site+5]
            stub = 6+struct.unpack('<i', before[1:])[0]
            memory = mmap.mmap(-1, stub+16, prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
            # 原 CALL 保持相对位移，目标桩转到计数回调；前后保持 ABI 栈对齐。
            memory[stub:stub+12] = b'\x48\xb8'+struct.pack('<Q', target)+b'\xff\xe0'
            entry = ctypes.CFUNCTYPE(None)(ctypes.addressof(ctypes.c_char.from_buffer(memory)))
            for data, count in ((original, 1), (modified, 0)):
                memory[:8] = b'\x53'+data[site:site+5]+b'\x5b\xc3'
                calls.clear()
                entry()
                self.assertEqual(len(calls), count)
            memory.close()

    def test_realtime_branch_does_not_enter_lockstep(self):
        binary = Path(__file__).resolve().parents[3]/'submodules/drone-race/ADRL/ADRL/Binaries/Linux/ADRL'
        if not binary.exists():
            self.skipTest('需要教师准备的已知 ADRL ELF')
        original = binary.read_bytes()
        modified = patch(original, disable_lockstep=True)
        branch = 16+LOCKSTEP_VA-0x2e1afd1
        cmp_start = branch-8
        for source, expected in ((original, [1, 0]), (modified, [0, 0])):
            code = bytearray(b'\x90'*1024)
            code[:10] = bytes.fromhex('41574989ffe9')+struct.pack('<i', cmp_start-10)
            code[16:21] = bytes.fromhex('31c0415fc3')
            site = LOCKSTEP_VA-0x200000
            code[cmp_start:branch+6] = source[site-8:site+6]
            code[branch+6:branch+14] = bytes.fromhex('b801000000415fc3')
            memory = mmap.mmap(-1, len(code), prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
            memory.write(code)
            call = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)(
                ctypes.addressof(ctypes.c_char.from_buffer(memory)))
            state = (ctypes.c_ubyte*0x900)()
            for active, result in enumerate(expected):
                state[0x8fc] = active
                self.assertEqual(call(ctypes.addressof(state)), result)
            memory.close()

    def test_both_control_states(self):
        getter_type = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)
        velocity_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_float, ctypes.c_float, ctypes.c_float)
        enabled = False
        seen = []
        table = (ctypes.c_void_p * 91)()
        api = (ctypes.c_void_p * 1)(ctypes.addressof(table))
        yaw = ctypes.c_int(123)

        @getter_type
        def getter(pointer):
            seen.append(('getter', pointer))
            return enabled

        @velocity_type
        def velocity(pointer, yaw_pointer, x, y, z):
            seen.append(('velocity', pointer, yaw_pointer, x, y, z))

        table[0x50//8] = ctypes.cast(getter, ctypes.c_void_p).value
        table[0x2d0//8] = ctypes.cast(velocity, ctypes.c_void_p).value
        memory = mmap.mmap(-1, len(GUARD), prot=mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC)
        memory.write(GUARD)
        entry = ctypes.addressof(ctypes.c_char.from_buffer(memory))
        guard = velocity_type(entry)
        guard(ctypes.addressof(api), ctypes.addressof(yaw), 5, 6, 7)
        self.assertEqual(seen, [('getter', ctypes.addressof(api))])
        enabled = True
        seen.clear()
        guard(ctypes.addressof(api), ctypes.addressof(yaw), 5, 6, 7)
        self.assertEqual(seen, [('getter', ctypes.addressof(api)),
            ('velocity', ctypes.addressof(api), ctypes.addressof(yaw), 0, 0, 0)])
        memory.close()

    def test_unknown_binary_rejected(self):
        with self.assertRaisesRegex(ValueError, '摘要'):
            patch(b'unknown ELF')


if __name__ == '__main__':
    unittest.main()
