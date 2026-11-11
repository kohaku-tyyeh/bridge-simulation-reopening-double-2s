#!/usr/bin/env python3
"""全樣本統計：平均 IMP、成對 bootstrap 95% 區間、BAM、勝和負、IMP 分布、大失分、
按原始續叫 Par 最佳終局集合分組的互斥貢獻、保護假設改變的牌。輸入 solve.py 的 results.jsonl。"""
import json, sys
from collections import Counter
from pathlib import Path
import numpy as np

SCEN = {'a': 'original', 'b': 'protect_32', 'c': 'protect_32_41'}
GROUPS = ['penalty_2SX', 'ns_make', 'ns_and_ew', 'ew_down', 'ew_part_make', 'ew_game_make', 'ns_down']

def side(o):  # '3CX-N' -> 'NS'
    return 'NS' if o.split('-')[1] in 'NS' else 'EW'

def is_game(con):
    lv, st = int(con[0]), con[1]
    return (st == 'N' and lv >= 3) or (st in 'HS' and lv >= 4) or (st in 'CD' and lv >= 5)

def group(r):
    x = r['a']; outs = x['outcomes']; s = x['score']
    if '2SX-E' in outs: return 'penalty_2SX'
    sides = {side(o) for o in outs}
    if sides == {'NS', 'EW'}: return 'ns_and_ew'
    if sides == {'NS'}: return 'ns_make' if s > 0 else 'ns_down'
    if s > 0: return 'ew_down'
    return 'ew_game_make' if is_game(x['rep'].split('-')[0]) else 'ew_part_make'

def fit8(pbn):
    hands = pbn[2:].split()  # N E S W
    n, s = hands[0].split('.'), hands[2].split('.')
    return max(len(a) + len(b) for a, b in zip(n, s))

def bins(imp):
    return {'<=-10': int((imp <= -10).sum()), '-9..-8': int(((imp >= -9) & (imp <= -8)).sum()),
            '-7..-1': int(((imp >= -7) & (imp <= -1)).sum()), '0': int((imp == 0).sum()),
            '+1..+7': int(((imp >= 1) & (imp <= 7)).sum()), '>=+8': int((imp >= 8).sum())}

def main(res_p, out_p, seed):
    rows = [json.loads(l) for l in Path(res_p).read_text().splitlines()]
    n = len(rows); rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(10000, n))   # 同一組重抽索引用於三個假設（成對）
    out = dict(n=n, bootstrap_seed=seed, bootstrap_reps=10000)
    for k, name in SCEN.items():
        imp = np.array([r[k]['imp'] for r in rows], float); bam = np.array([r[k]['bam'] for r in rows])
        bi = imp[idx].mean(1); bb = bam[idx].mean(1)
        out[name] = dict(mean_imp=round(imp.mean(), 4), sd_imp=round(imp.std(ddof=1), 4),
                         ci95_imp=[round(x, 4) for x in np.percentile(bi, [2.5, 97.5])],
                         bam=round(bam.mean(), 5), ci95_bam=[round(x, 5) for x in np.percentile(bb, [2.5, 97.5])],
                         win_tie_loss=[int((bam == 1).sum()), int((bam == .5).sum()), int((bam == 0).sum())],
                         imp_bins=bins(imp), imp_distribution={int(a): b for a, b in sorted(Counter(imp.astype(int)).items())},
                         mean_score_double=round(np.mean([r[k]['score'] for r in rows]), 2))
    out['mean_score_pass'] = round(np.mean([r['pass_score'] for r in rows]), 2)
    out['pass_2S_down'] = sum(r['pass_score'] > 0 for r in rows)
    # 原始續叫 Par 的互斥分組
    g = {}
    for r in rows:
        gr = group(r); d = g.setdefault(gr, dict(boards=0, imp_sum=0, reps=Counter(), transitions=Counter()))
        d['boards'] += 1; d['imp_sum'] += r['a']['imp']; d['reps'][r['a']['rep']] += 1
        d['transitions'][(r['pass_score'], r['a']['score'], r['a']['imp'])] += 1
    comp = {}
    for gr in GROUPS:
        d = g.get(gr, dict(boards=0, imp_sum=0, reps=Counter(), transitions=Counter()))
        comp[gr] = dict(boards=d['boards'], contribution=round(d['imp_sum'] / n, 4),
                        top_rep_contracts=d['reps'].most_common(6),
                        top_transitions=[[list(t), c] for t, c in d['transitions'].most_common(6)])
    out['components_original'] = comp
    assert sum(c['boards'] for c in comp.values()) == n
    assert abs(sum(d['imp_sum'] for d in g.values()) / n - out['original']['mean_imp']) < 1e-3
    # 子群細節
    a = [(r, r['a']) for r in rows]
    out['detail'] = dict(
        penalty_by_pass_score=dict(Counter(r['pass_score'] for r, x in a if group(r) == 'penalty_2SX')),
        ns_down_no_8fit=sum(1 for r, x in a if group(r) == 'ns_down' and fit8(r['pbn']) < 8),
        ns_down_score_m100=sum(1 for r, x in a if group(r) == 'ns_down' and x['score'] == -100),
        ns_down_loss_ge8=sum(1 for r, x in a if group(r) == 'ns_down' and x['imp'] <= -8),
        loss_ge8=sum(1 for r, x in a if x['imp'] <= -8),
        loss_ge8_by_group=dict(Counter(group(r) for r, x in a if x['imp'] <= -8)),
        loss_ge10_by_group=dict(Counter(group(r) for r, x in a if x['imp'] <= -10)),
        win_ge8=sum(1 for r, x in a if x['imp'] >= 8),
        raw_win_zero_imp=sum(1 for r, x in a if x['diff'] > 0 and x['imp'] == 0),
        raw_win_zero_imp_m100_vs_m110=sum(1 for r, x in a if x['diff'] > 0 and x['imp'] == 0 and x['score'] == -100 and r['pass_score'] == -110),
        raw_win=sum(1 for r, x in a if x['diff'] > 0),
        ns_and_ew_3NT=sum(1 for r, x in a if group(r) == 'ns_and_ew' and any(o.startswith('3N') and side(o) == 'NS' for o in x['outcomes'])),
        ew_part_3S=sum(1 for r, x in a if group(r) == 'ew_part_make' and x['rep'] == '3S-E'),
        unique_best_contract={name: sum(len(r[k]['outcomes']) == 1 for r in rows) for k, name in SCEN.items()})
    # 保護假設改變的牌
    for k, name in (('b', 'protect_32'), ('c', 'protect_32_41')):
        ch = [r for r in rows if r[k]['score'] != r['a']['score']]
        out[name]['changed_vs_original'] = len(ch)
        out[name]['decreased_vs_original'] = sum(r[k]['score'] < r['a']['score'] for r in ch)
        out[name]['top_changes'] = [[list(t), c] for t, c in Counter((r['a']['score'], r[k]['score']) for r in ch).most_common(6)]
        out[name]['loss_ge10_same_as_original'] = sum(1 for r in rows if r['a']['imp'] <= -10 and r[k]['imp'] == r['a']['imp'])
        out[name]['changed_contract_same_score'] = sum(1 for r in rows if r[k]['score'] == r['a']['score'] and r[k]['rep'] != r['a']['rep'])
    Path(out_p).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o)) + '\n')
    return out

if __name__ == '__main__':
    o = main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 20261112)
    print(json.dumps(o, ensure_ascii=False, indent=1, default=str)[:6000])
