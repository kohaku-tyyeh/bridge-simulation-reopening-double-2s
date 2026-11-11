#!/usr/bin/env python3
"""DD（多 worker）→ 續叫 Par（C++，三種假設）→ 逐副結果。
輸入 deals.jsonl（board, pbn）。dd.jsonl 依牌號寫出並可接續（已完成的牌號略過）。"""
import argparse, json, subprocess, sys, os
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as C

def dd_worker(item):
    import dds
    dds.set_threads(1)
    board, pbn = item
    h = C.parse_pbn(pbn); C.check_deal(h)
    t = dds.table(pbn)
    # DD 座位花色對應檢查：同方兩家作莊墩數 + 對方作莊墩數不須相等，但 N/S 作莊墩數 + E/W 防守墩數 = 13
    for s in 'SHDCN':
        for x in 'NESW':
            assert 0 <= t[(s, x)] <= 13
    return board, pbn, {f'{s}{x}': t[(s, x)] for s in 'SHDCN' for x in 'NESW'}

def run_dd(deals, out, workers):
    done = set()
    if out.exists():
        for l in out.read_text().splitlines():
            done.add(json.loads(l)['board'])
    todo = [(d['board'], d['pbn']) for d in deals if d['board'] not in done]
    with open(out, 'a') as f, Pool(workers) as p:
        for k, (b, pbn, t) in enumerate(p.imap(dd_worker, todo, chunksize=4)):
            f.write(json.dumps(dict(board=b, pbn=pbn, dd=t)) + '\n')
            if k % 200 == 0: f.flush(); print('dd', k, len(todo), flush=True)

def run_par(dd_rows, prot, exe, cache, workers):
    """C++ 搜尋；輸出原文快取在 cache（存在就重用），分成 workers 份並行。"""
    if not cache.exists():
        lines = []
        for r in dd_rows:
            h = C.parse_pbn(r['pbn'])
            dd = {(k[0], k[1]): v for k, v in r['dd'].items()}
            lines.append(C.input_line(r['board'], dd, h, prot) + '\n')
        chunks = [lines[i::workers] for i in range(workers)]
        procs = [subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                 for _ in chunks]
        import threading
        outs = [None] * len(procs)
        def go(i):
            outs[i] = procs[i].communicate(''.join(chunks[i]))[0]
            assert procs[i].returncode == 0
        ts = [threading.Thread(target=go, args=(i,)) for i in range(len(procs))]
        [t.start() for t in ts]; [t.join() for t in ts]
        tmp = cache.with_suffix('.tmp'); tmp.write_text(''.join(outs)); os.replace(tmp, cache)
    res = {}
    for l in cache.read_text().splitlines():
        head, path, final = l.split(' | ')
        b, v, n, outs = head.split()
        res[int(b)] = dict(value=int(v), outcomes=outs.split(';'), path=path.split(),
                           rep=final.split()[0], nodes=int(final.split()[1]))
    assert len(res) == len(dd_rows)
    return res

AUCTION = ['P', '1S', 'X', 'P', '1NT', '2H', 'P', '2S', 'P', 'P']
def legal_check(prefix_and_cont):
    """叫序合法：叫品遞增、X 只對敵方未加倍叫品、XX 只對敵方的 X、結尾三個 Pass。"""
    order = ['C', 'D', 'H', 'S', 'N']
    last = None; last_side = None; dbl = 0
    for i, c in enumerate(prefix_and_cont):
        side = i % 2  # 北家發牌：N=0, E=1, S=0, W=1
        if c == 'P': continue
        if c == 'X':
            assert last is not None and last_side != side and dbl == 0, (i, c); dbl = 1
        elif c == 'XX':
            assert dbl == 1 and last_side == side, (i, c); dbl = 2
        else:
            c2 = c.replace('NT', 'N')
            v = (int(c2[0]) - 1) * 5 + order.index(c2[1])
            assert last is None or v > last, (i, c); last = v; last_side = side; dbl = 0
    assert prefix_and_cont[-3:] == ['P', 'P', 'P']

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--deals', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--exe', default=str(Path(__file__).parent.parent / 'build/contpar'))
    a = ap.parse_args()
    deals = [json.loads(l) for l in a.deals.read_text().splitlines()]
    a.out.mkdir(parents=True, exist_ok=True)
    run_dd(deals, a.out / 'dd.jsonl', a.workers)
    rows = {}
    for l in (a.out / 'dd.jsonl').read_text().splitlines():
        r = json.loads(l); rows[r['board']] = r
    rows = [rows[d['board']] for d in deals]
    par = {p: run_par(rows, p, a.exe, a.out / f'par_{p}.txt', a.workers) for p in 'abc'}
    with open(a.out / 'results.jsonl', 'w') as f:
        for r in rows:
            b = r['board']; dd = {(k[0], k[1]): v for k, v in r['dd'].items()}
            ps = C.score_ns('2S', 'E', dd)
            assert (ps > 0) == (dd[('S', 'E')] < 8), 'pass score sign'
            out = dict(board=b, pbn=r['pbn'], dd=r['dd'], pass_score=ps)
            for p in 'abc':
                x = par[p][b]
                # 以 Python 計分重算代表路徑終局，與 C++ 值對照
                rep = x['rep']; con, decl = rep.split('-')
                assert C.score_ns(con, decl, dd) == x['value'], (b, p, rep)
                legal_check(AUCTION + ['X'] + x['path'])
                diff = x['value'] - ps
                out[p] = dict(score=x['value'], outcomes=x['outcomes'], rep=rep,
                              continuation=x['path'], diff=diff, imp=C.imp(diff),
                              bam=1.0 if diff > 0 else 0.5 if diff == 0 else 0.0)
            f.write(json.dumps(out) + '\n')
    print('done', len(rows))

if __name__ == '__main__':
    main()
