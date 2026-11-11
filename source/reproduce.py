#!/usr/bin/env python3
"""檢查與重新計算的入口。

  python3 source/reproduce.py --mode verify            只讀 data/：雜湊、篩牌、牌張、叫序合法、計分、IMP/BAM、統計摘要
  python3 source/reproduce.py --mode tests             編譯續叫搜尋，跑小局面窮舉 oracle 與化簡對照
  python3 source/reproduce.py --mode sample --output D --count N
                                                       用同一種子重抽前 N 副，重算 DD 與續叫，與 data/ 前 N 副逐副比對
  python3 source/reproduce.py --mode full --output D   從種子重抽一萬副並全部重算，再與 data/ 逐副比對
"""
import argparse, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
SRC = Path(__file__).resolve().parent; ROOT = SRC.parent
sys.path.insert(0, str(SRC)); sys.path.insert(0, str(SRC / 'filters'))
import common as C

SCEN = {'original': 'a', 'protect_32': 'b', 'protect_32_41': 'c'}

def compile_search(build):
    build.mkdir(parents=True, exist_ok=True); exe = build / 'contpar'
    cxx = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
    cmd = [cxx] if cxx else [sys.executable, '-m', 'ziglang', 'c++']
    subprocess.run(cmd + ['-std=c++17', '-O2', '-o', str(exe), str(SRC / 'contpar.cpp')], check=True)
    return exe

def legal(auction):
    order = 'CDHSN'; last = None; last_side = None; dbl = 0
    for i, c in enumerate(auction):
        side = i % 2
        if c == 'P': continue
        if c == 'X': assert last is not None and last_side != side and dbl == 0; dbl = 1
        elif c == 'XX': assert dbl == 1 and last_side == side; dbl = 2
        else:
            v = (int(c[0]) - 1) * 5 + order.index(c[1]); assert last is None or v > last
            last, last_side, dbl = v, side, 0
    assert auction[-3:] == ['P', 'P', 'P'] and len(auction) > 3

def verify():
    import filter_deals as F
    import numpy as np
    bad = []
    for line in (ROOT / 'MANIFEST.sha256').read_text().splitlines():
        h, p = line.split('  ', 1)
        if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != h: bad.append(p)
    assert not bad, f'雜湊不符：{bad}'
    rules = json.loads((SRC / 'filters' / 'rules.json').read_text())
    rows = [json.loads(l) for l in (ROOT / 'data' / 'results.jsonl').read_text().splitlines()]
    imps = {k: [] for k in SCEN}; bams = {k: [] for k in SCEN}
    for i, r in enumerate(rows, 1):
        assert r['board'] == i
        h = C.parse_pbn(r['pbn']); C.check_deal(h)
        H = {s: F.Hand(tuple(h[s])) for s in 'NESW'}
        assert not F.deal_failures(H, rules)
        t = r['dd_table']['tricks']
        dd = {(s, x): t[a][b] for a, s in enumerate('CDHSN') for b, x in enumerate('NESW')}
        p = r['pass_branch']; ps = C.score_ns('2S', 'E', dd)
        assert p['score_ns'] == ps and (ps > 0) == (dd[('S', 'E')] < 8)
        legal(p['full_auction'])
        for name in SCEN:
            d = r['double_branches'][name]; legal(d['full_auction'])
            assert d['full_auction'][:11] == ['P', '1S', 'X', 'P', '1NT', '2H', 'P', '2S', 'P', 'P', 'X']
            c = d['contract']; con = f"{c['level']}{c['strain']}{'X' * c['doubled']}"
            assert C.score_ns(con, c['declarer'], dd) == d['score_ns']
            for o in d['optimal_contracts']:
                assert C.score_ns(f"{o['level']}{o['strain']}{'X' * o['doubled']}", o['declarer'], dd) == d['score_ns']
            diff = d['score_ns'] - ps
            assert d['delta_score_ns'] == diff and d['imp'] == C.imp(diff)
            assert d['bam'] == (1.0 if diff > 0 else 0.5 if diff == 0 else 0.0)
            imps[name].append(d['imp']); bams[name].append(d['bam'])
    summ = json.loads((ROOT / 'audits' / 'summary.json').read_text())
    for name in SCEN:
        assert round(float(np.mean(imps[name])), 4) == summ[name]['mean_imp']
        assert round(float(np.mean(bams[name])), 5) == summ[name]['bam']
    out = dict(boards=len(rows), manifest_files_checked=len((ROOT / 'MANIFEST.sha256').read_text().splitlines()),
               checks=['MANIFEST 雜湊', '52 張完整不重複、南家不變', '篩牌條件全部通過', 'Pass 分數與正負號',
                       '叫序合法並以三個 Pass 結束', '代表終局與全部最佳終局的分數', '分差、IMP、BAM 換算',
                       '平均 IMP 與 BAM 與 audits/summary.json 相同'],
               mean_imp={n: summ[n]['mean_imp'] for n in SCEN}, bam={n: summ[n]['bam'] for n in SCEN}, result='OK')
    print(json.dumps(out, ensure_ascii=False, indent=1)); return out

def tests(build):
    exe = compile_search(build); env = dict(os.environ, CONTPAR=str(exe))
    subprocess.run([sys.executable, str(SRC / 'oracle_test.py'), '600'], check=True, env=env)
    rows = [json.loads(l) for l in (ROOT / 'data' / 'results.jsonl').read_text().splitlines()][:25]
    tmp = build / 'dd_first25.jsonl'
    with open(tmp, 'w') as f:
        for r in rows:
            t = r['dd_table']['tricks']
            f.write(json.dumps(dict(board=r['board'], pbn=r['pbn'], dd={s + x: t[a][b] for a, s in enumerate('CDHSN')
                                                                        for b, x in enumerate('NESW')})) + '\n')
    subprocess.run([sys.executable, str(SRC / 'collapse_check.py'), str(tmp), '25'], check=True, env=env)

def recompute(out, count):
    meta = json.loads((ROOT / 'metadata.json').read_text())
    exe = compile_search(out / 'build')
    subprocess.run([sys.executable, str(SRC / 'sample.py'), '--seed', str(meta['seeds']['sampling']),
                    '--count', str(count), '--out', str(out / 'run')], check=True)
    subprocess.run([sys.executable, str(SRC / 'solve.py'), '--deals', str(out / 'run' / 'deals.jsonl'),
                    '--out', str(out / 'run'), '--exe', str(exe)], check=True)
    subprocess.run([sys.executable, str(SRC / 'export_data.py'), str(out / 'run'), str(out / 'data')], check=True)
    mine = (out / 'data' / 'results.jsonl').read_text().splitlines()
    ref = (ROOT / 'data' / 'results.jsonl').read_text().splitlines()[:count]
    diff = [i + 1 for i, (a, b) in enumerate(zip(mine, ref)) if a != b]
    print(f'比對 {len(mine)} 副：不一致 {len(diff)} 副 {diff[:20]}')
    return not diff

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mode', choices=['verify', 'tests', 'sample', 'full'], default='verify')
    ap.add_argument('--output', type=Path)
    ap.add_argument('--count', type=int, default=200)
    a = ap.parse_args()
    if a.mode == 'verify': verify()
    elif a.mode == 'tests': tests(a.output or ROOT / 'build')
    else:
        if not a.output: ap.error('--output 必填（新目錄）')
        ok = recompute(a.output, a.count if a.mode == 'sample' else 10000)
        sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
