#!/usr/bin/env python3
"""全範圍（到 7NT）真實牌：化簡版與不化簡版的值與最佳終局集合必須相同。"""
import json, subprocess, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
EXE = os.environ.get('CONTPAR', str(Path(__file__).resolve().parent.parent / 'build/contpar'))
import common as C
n = int(sys.argv[2]); rows = [json.loads(l) for l in open(sys.argv[1])][:n]
bad = 0
for p in 'abc':
    lines = ''.join(C.input_line(r['board'], {(k[0], k[1]): v for k, v in r['dd'].items()},
                                 C.parse_pbn(r['pbn']), p) + '\n' for r in rows)
    o = {}
    for fl in ([], ['--nocollapse']):
        out = subprocess.run([EXE] + fl, input=lines, capture_output=True, text=True, check=True).stdout
        o[tuple(fl)] = [l.split(' | ')[0].split() for l in out.splitlines()]
    for x, y in zip(o[()], o[('--nocollapse',)]):
        ex = set(x[3].split(';'))
        if x[1] != y[1] or ex != set(y[3].split(';')): bad += 1; print('MISMATCH', p, x, y)
print('collapse check boards', n, 'x3, mismatches', bad)
