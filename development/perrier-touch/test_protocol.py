#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
fixtures=HERE/'fixtures'
fixtures.mkdir(exist_ok=True)
sources={
    'sysinfo.bin':ROOT/'evidence/perrier-touch-sysinfo-2026-11-09.txt',
    'reports.bin':ROOT/'development/runs/20261109T092412Z-perrier-simpledrm-trial-237d0c/serial.log'
}
sysinfo=bytes.fromhex(re.search(r'SYSINFO_DATA ([0-9a-f]+)',sources['sysinfo.bin'].read_text())[1])
reports=b''.join(bytes.fromhex(h) for h in re.findall(r'PERRIER_TOUCH_CAPTURE sample=\d+ irq=\d data=([0-9a-f]+)',sources['reports.bin'].read_text()))
(fixtures/'sysinfo.bin').write_bytes(sysinfo)
(fixtures/'reports.bin').write_bytes(reports)
(fixtures/'manifest.json').write_text(json.dumps({name:{'source':str(path.relative_to(ROOT)),
    'sha256':hashlib.sha256((fixtures/name).read_bytes()).hexdigest()}
    for name,path in sources.items()},indent=2)+'\n')
binary=HERE/'test-protocol'
subprocess.run(['clang','-std=c11','-g','-O1','-Wall','-Wextra','-Werror',
    '-fsanitize=address,undefined','-fno-omit-frame-pointer',
    str(HERE/'test_protocol.c'),'-o',str(binary)],check=True)
result=subprocess.run([str(binary),str(fixtures/'sysinfo.bin'),str(fixtures/'reports.bin')],
                      text=True,capture_output=True,
                      env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
(HERE/'test-protocol.log').write_text(result.stdout+result.stderr)
result.check_returncode()
print(result.stdout,end='')
