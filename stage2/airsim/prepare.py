#!/usr/bin/env python3
"""PC：为已知 ADRL v1.0 创建独立兼容副本，不修改原始场景包。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHA256 = '094ad6b3cb8f55b63a05ab6ca9ee91e18c3eac1d21b64b20451302ba427c68bc'
# clearTrajectory() 中唯一的 moveByVelocityInternal 虚调用。
CALL_VA = 0x2d933a6
EXPECTED = bytes.fromhex('ff90d0020000')
# 保留 rdi/rsi 与栈对齐，调用 vtable[0x50] 的 isApiControlEnabled()。
# false: 返回清理逻辑；true: 恢复零速度参数并尾调用原 vtable[0x2d0]。
GUARD = bytes.fromhex('57564883ec08488b07ff505084c0488d6424085e5f7412488b070f57c00f57c90f57d2ffa0d0020000c3')


LOCKSTEP_VA = 0x2e1b2c2
LOCKSTEP_EXPECTED = bytes.fromhex('0f8509fdffff')
# SITL 已自行启用模拟器；旧包设置/清除 HIL 标志时发送 custom main mode=0。
SITL_HIL_CALLS = {0x2e1b8ab: bytes.fromhex('e820baa204'),
                  0x2e17c9b: bytes.fromhex('e830f6a204')}


def patch(data, *, disable_lockstep=False):
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError('场景 ELF 摘要不匹配；拒绝将固定地址补丁用于其他版本')
    data = bytearray(data)
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 54)
    segments = []
    for i in range(phnum):
        pos = phoff+i*phsize
        kind, flags, offset, va, _, size, memsize, _ = struct.unpack_from('<IIQQQQQQ', data, pos)
        if kind == 1:
            segments.append((pos, flags, offset, va, size, memsize))
    segment = next(s for s in segments if s[1] & 1 and s[3] <= CALL_VA < s[3]+s[4])
    pos, _, offset, va, size, memsize = segment
    call_offset = offset+CALL_VA-va
    if data[call_offset:call_offset+6] != EXPECTED or size != memsize:
        raise ValueError('补丁位置或 ELF 段布局不匹配')
    # 利用可执行 LOAD 段尾与下一段之间的未使用文件填充；不覆盖原指令/数据。
    guard_va, guard_offset = va+size, offset+size
    next_offset = min(s[2] for s in segments if s[2] > offset)
    if guard_offset+len(GUARD) > next_offset or any(data[guard_offset:guard_offset+len(GUARD)]):
        raise ValueError('ELF 段尾没有预期的零填充空间')
    data[guard_offset:guard_offset+len(GUARD)] = GUARD
    struct.pack_into('<QQ', data, pos+32, size+len(GUARD), memsize+len(GUARD))
    data[call_offset:call_offset+6] = b'\xe8'+struct.pack('<i', guard_va-CALL_VA-5)+b'\x90'
    if disable_lockstep:
        # 此旧包依据 HIL flags/时间戳自动启用锁步，未检查配置的 LockStep。
        # 保留执行器数据更新，跳过自动启用锁步；由 ScalableClock 实时推进。
        site = offset+LOCKSTEP_VA-va
        if data[site:site+6] != LOCKSTEP_EXPECTED:
            raise ValueError('旧包锁步分支指令不匹配')
        data[site:site+6] = b'\xe9'+struct.pack('<i', 0x2e1afd1-LOCKSTEP_VA-5)+b'\x90'
        for address, expected in SITL_HIL_CALLS.items():
            site = offset+address-va
            if data[site:site+5] != expected:
                raise ValueError('旧包 SITL HIL 模式请求指令不匹配')
            # 仅省略两个冗余的 HIL 标志请求；正常模式切换与 Offboard 不改。
            data[site:site+5] = b'\x90'*5
    return bytes(data)


def prepare(source, destination, *, disable_lockstep=False):
    source = source.resolve(strict=True)
    for relative in ('Engine', 'ADRL/Content'):
        if not (source/relative).is_dir():
            raise ValueError(f'场景资源目录缺失：{source/relative}')
    original = source/'ADRL/Binaries/Linux/ADRL'
    patched = patch(original.read_bytes(), disable_lockstep=disable_lockstep)
    executable = destination/'ADRL/Binaries/Linux/ADRL'
    executable.parent.mkdir(parents=True, exist_ok=True)
    if executable.exists() and executable.read_bytes() != patched:
        raise RuntimeError(f'拒绝覆盖未知副本：{executable}')
    if not executable.exists():
        executable.write_bytes(patched)
        executable.chmod(0o755)
    for relative in ('Engine', 'ADRL/Content', 'ADRL/Binaries/Linux/ADRL.sym'):
        target = source/relative
        if not target.exists():
            continue
        link = destination/relative
        if link.is_symlink() and link.resolve() == target.resolve():
            continue
        if link.exists() or link.is_symlink():
            raise RuntimeError(f'拒绝覆盖资源：{link}')
        link.symlink_to(target, target_is_directory=target.is_dir())
    manifest = dict(source=str(source), source_sha256=SOURCE_SHA256,
                    patched_sha256=hashlib.sha256(patched).hexdigest(),
                    disable_lockstep=disable_lockstep,
                    lockstep_branch_va=hex(LOCKSTEP_VA) if disable_lockstep else None,
                    skip_sitl_hil_requests=disable_lockstep,
                    guard='clearTrajectory: only send zero velocity when API control is enabled')
    (destination/'compatibility.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return executable


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'submodules/drone-race/ADRL')
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/stage2-airsim/package')
    args = parser.parse_args()
    print(prepare(args.source, args.output.resolve()))
