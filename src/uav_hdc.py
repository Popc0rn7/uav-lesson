"""PC 共用 HDC shell：显式目标与远端退出码核验。"""
import re
import subprocess
import uuid

def shell(target, script, timeout=30):
    if not isinstance(target,str) or not target.strip() or target.startswith('-'):
        raise ValueError('需要显式的 HDC target')
    marker='UAV_STAGE3_'+uuid.uuid4().hex
    wrapped='('+script+'); rc=$?; printf "\\n'+marker+':%s\\n" "$rc"'
    result=subprocess.run(['hdc','-t',target,'shell',wrapped],capture_output=True,text=True,timeout=timeout)
    result.check_returncode()
    match=re.search(r'\n'+marker+r':(\d+)\s*$',result.stdout)
    if not match or match[1]!='0':
        raise RuntimeError('板端命令失败或缺少退出码：'+(result.stdout+result.stderr)[-3000:])
    return result.stdout[:match.start()].strip()
