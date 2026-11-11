#!/usr/bin/env python3
"""小局面窮舉 oracle：不記憶、不化簡，逐一列舉所有合法叫牌序列；
莊家由完整叫序重新判定（該方第一個叫該王牌者）。與 C++ contpar 比對值與最佳終局集合。"""
import random, subprocess, sys, functools, os
from pathlib import Path
sys.path.insert(0, __file__.rsplit('/', 1)[0])
EXE = os.environ.get('CONTPAR', str(Path(__file__).resolve().parent.parent / 'build/contpar'))
from common import score_decl
SEATS = 'NESW'; SN = 'CDHSN'

def oracle(T, start, maxbid, prot, nsLen, ewMax):
    bid0, decl0, dbl0, passes0, toAct0, first0 = start
    # 歷史以 (caller, call) 串列表示；起始的第一叫者轉成歷史前綴
    prefix = []
    for i, f in enumerate(first0):
        if f >= 0: prefix.append((f, i % 5))
    def declarer(hist, bid, bidder):
        side = bidder % 2; strain = bid % 5
        for c, s in prefix + hist:
            if c % 2 == side and s == strain: return c
        raise AssertionError
    def score(bid, decl, dbl):
        side = decl % 2
        s = score_decl(bid // 5 + 1, SN[bid % 5], dbl, T[bid % 5][decl], side == 1)
        return s if side == 0 else -s
    def protected(bid, decl):
        if not prot or decl % 2: return False
        lv, st = bid // 5 + 1, bid % 5
        return lv == 3 and st != 4 and nsLen[st] == 8 and (prot >> ewMax[st]) & 1
    def rec(bid, decl, dbl, passes, to, hist):
        """回傳 (值, 最佳終局集合)。"""
        res = []
        side = to % 2
        # Pass
        if passes + 1 == 3: res.append((score(bid, decl, dbl), {(bid, decl, dbl)}))
        else: res.append(rec(bid, decl, dbl, passes + 1, (to + 1) % 4, hist))
        if dbl == 0 and decl % 2 != side and not (side == 1 and protected(bid, decl)):
            res.append(rec(bid, decl, 1, 0, (to + 1) % 4, hist))
        if dbl == 1 and decl % 2 == side:
            res.append(rec(bid, decl, 2, 0, (to + 1) % 4, hist))
        for b in range(bid + 1, maxbid + 1):
            h2 = hist + [(to, b % 5)]
            res.append(rec(b, declarer(h2, b, to), 0, 0, (to + 1) % 4, h2))
        best = max(v for v, _ in res) if side == 0 else min(v for v, _ in res)
        outs = set().union(*[o for v, o in res if v == best])
        return best, outs
    return rec(bid0, decl0, dbl0, passes0, toAct0, [])

def fmt(T, o, collapse):
    bid, decl, dbl = o
    r = f'{bid//5+1}{SN[bid%5]}' + 'X' * dbl + '-' + SEATS[decl]
    p = (decl + 2) % 4
    if collapse and T[bid % 5][decl] == T[bid % 5][p]:
        a, b = sorted([decl, p]); r = r.rsplit('-', 1)[0] + '-' + SEATS[a] + '/' + SEATS[b]
    return r

def run_engine(lines, flags):
    r = subprocess.run([EXE] + flags, input=''.join(lines), capture_output=True, text=True, check=True)
    return r.stdout.splitlines()

def main(ncases=300, seed=99):
    rng = random.Random(seed)
    cases = []
    for k in range(ncases):
        T = [[rng.randint(3, 11) for _ in range(4)] for _ in range(5)]
        for st in range(5):  # 讓部分同伴墩數相同，測化簡
            for sd in range(2):
                if rng.random() < 0.6: T[st][sd + 2] = T[st][sd]
        nsLen = [rng.choice([6, 7, 8, 8, 9]) for _ in range(4)]
        ewMax = [rng.choice([3, 4, 5]) for _ in range(4)]
        prot = rng.choice([0, 8, 24])
        if k % 3 == 0:  # 正式起點 2♠X，叫品上限 3♣/3♦
            start = (8, 1, 1, 0, 3, [-1, -1, -1, -1, 0, -1, -1, 1, 1, -1]); maxbid = rng.choice([10, 11])
        else:           # 隨機起點（含三線南北合約，可測保護）
            bid = rng.randint(5, 30); maxbid = min(34, bid + rng.choice([1, 2, 3]))
            if rng.random() < 0.5: bid = rng.choice([10, 11, 12, 13]); maxbid = bid + 2
            decl = rng.randint(0, 3); dbl = rng.randint(0, 2); passes = rng.randint(0, 2)
            first = [-1] * 10
            for i in range(10):
                if rng.random() < 0.3: first[i] = rng.choice([i // 5, i // 5 + 2])
            first[(decl % 2) * 5 + bid % 5] = decl
            last_side = decl % 2 if dbl != 1 else 1 - decl % 2
            last = rng.choice([last_side, last_side + 2])
            start = (bid, decl, dbl, passes, (last + 1 + passes) % 4, first)
        cases.append((T, start, maxbid, prot, nsLen, ewMax))
    bad = 0
    for flags, collapse in (([], True), (['--nocollapse'], False)):
        groups = {}
        for i, c in enumerate(cases): groups.setdefault(c[2], []).append(i)
        out = {}
        for mb, idxs in groups.items():
            lines = []
            for i in idxs:
                T, start, maxbid, prot, nsLen, ewMax = cases[i]
                t = [T[st][h] for st in range(5) for h in range(4)]
                lines.append(' '.join(map(str, [i] + t + nsLen + ewMax + [prot] + list(start[:5]) + start[5])) + '\n')
            for l in run_engine(lines, flags + ['--maxbid', str(mb)]):
                out[int(l.split()[0])] = l
        for i, c in enumerate(cases):
            T, start, maxbid, prot, nsLen, ewMax = c
            v, outs = oracle(*c)
            f = out[i].split()
            ev = int(f[1]); eouts = set(f[3].split(';'))
            ooo = {fmt(T, o, False) for o in outs}
            if ev != v or eouts != ooo:
                bad += 1
                print('MISMATCH', flags, i, c, v, sorted(ooo), out[i])
    print(f'oracle cases {len(cases)} x 2 modes; mismatches {bad}')
    return bad

if __name__ == '__main__':
    sys.exit(1 if main(int(sys.argv[1]) if len(sys.argv) > 1 else 300) else 0)
