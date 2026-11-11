#!/usr/bin/env python3
"""Descriptive hidden-hand factors in the latest DK 10,000-deal experiment.

Reads saved deals and action outcomes only. These are post-hoc diagnostics,
not information available to South and not causal estimates or fitted bidding
probabilities. All partitions are specified before inspecting outcomes.
"""
import argparse
from collections import defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from heart_strength_analysis import fixed_effects

HCP = dict(A=4, K=3, Q=2, J=1)


def heart_category(hearts):
    if 'A' in hearts:
        return 'A_present'
    if 'K' in hearts and 'Q' in hearts:
        return 'KQ_or_KQJ'
    if 'K' in hearts:
        return 'K_or_KJ'
    if 'Q' in hearts:
        return 'Q_or_QJ'
    if 'J' in hearts:
        return 'J_only'
    return 'no_AKQJ'


def summarize(rows, denominator):
    n = len(rows)
    y = np.array([r['delta_imp'] for r in rows], dtype=float)
    sem = float(y.std(ddof=1) / np.sqrt(n)) if n > 1 else None
    mean = float(y.mean())
    return dict(n=n, frequency=n/denominator, sum_imp=int(y.sum()),
                mean_imp=mean, contribution_per_all_deal=float(y.sum()/denominator),
                mean_imp_normal95=[mean-1.959963984540054*sem, mean+1.959963984540054*sem]
                if n >= 100 else None,
                normal_ci_shown=n >= 100,
                bam_mean=float(np.mean([r['bam_points'] for r in rows])),
                raw_wins=sum(r['delta_ns']>0 for r in rows),
                raw_ties=sum(r['delta_ns']==0 for r in rows),
                raw_losses=sum(r['delta_ns']<0 for r in rows),
                loss8_count=int((y <= -8).sum()), loss8_rate=float((y <= -8).mean()),
                loss10_count=int((y <= -10).sum()), loss10_rate=float((y <= -10).mean()),
                mean_north_hcp=float(np.mean([r['north_hcp'] for r in rows])),
                mean_east_hcp=float(np.mean([r['east_hcp'] for r in rows])),
                mean_west_hcp=float(np.mean([r['west_hcp'] for r in rows])))


def partition(rows, fields, denominator):
    groups = defaultdict(list)
    for row in rows:
        key = '|'.join(str(row[f]) for f in fields)
        groups[key].append(row)
    result = {key:summarize(group, denominator) for key,group in sorted(groups.items())}
    assert sum(g['n'] for g in result.values()) == len(rows)
    assert sum(g['sum_imp'] for g in result.values()) == sum(r['delta_imp'] for r in rows)
    return result


def adjusted_fit(rows, features, strata_fields, outcome):
    result = fixed_effects(rows, features, strata_fields, outcome)
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[f] for f in strata_fields)].append(row)
    result['support_by_feature'] = {}
    for name, feature in features:
        varying = [group for group in groups.values()
                   if len({feature(row) for row in group}) > 1]
        result['support_by_feature'][name] = dict(
            strata_with_variation=len(varying),
            deals_in_strata_with_variation=sum(map(len, varying)))
    return result


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', nargs='?', type=Path, default=root/'run_v5_10000')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    run = args.run_dir
    output = args.output or run/'contract_analysis'
    deals = json.loads((run/'deals.json').read_text())['deals']
    outcomes = {r['number']:r for r in map(json.loads,(run/'results.jsonl').read_text().splitlines())}
    rows = []
    for d in deals:
        n,e,w = (d['hands'][s] for s in 'NEW')
        outcome = outcomes[d['number']]
        h = n['suits']['H']
        s = n['suits']['S']
        rows.append(dict(number=d['number'], delta_imp=outcome['delta_imp'],
                         delta_ns=outcome['delta_ns'], bam_points=outcome['bam_points'],
                         loss8=int(outcome['delta_imp'] <= -8),
                         loss10=int(outcome['delta_imp'] <= -10),
                         north_hcp=n['hcp'], north_shape='-'.join(map(str,n['shape_SHDC'])),
                         heart_length=len(h), heart_honors=''.join(c for c in 'AKQJ' if c in h) or '-',
                         heart_category=heart_category(h), has_heart_ace=int('A' in h),
                         north_spade_length=len(s),north_spade_hcp=sum(HCP.get(c,0) for c in s),
                         north_best_minor_fit=4+max(len(n['suits']['D']),len(n['suits']['C'])),
                         north_minor_lengths=f"{len(n['suits']['D'])}-{len(n['suits']['C'])}",
                         east_hcp=e['hcp'],east_major_shape='-'.join(map(str,e['shape_SHDC'][:2])),
                         west_spade_length=len(w['suits']['S']),west_hcp=w['hcp']))
    assert len(rows)==10000 and sum(r['delta_imp'] for r in rows)==4889
    specs = {
        'north_heart_length':['heart_length'],
        'north_heart_category':['heart_category'],
        'north_heart_category_by_length':['heart_length','heart_category'],
        'north_shape':['north_shape'],
        'north_hcp':['north_hcp'],
        'north_spade_length':['north_spade_length'],
        'north_best_minor_fit':['north_best_minor_fit'],
        'north_minor_lengths':['north_minor_lengths'],
        'east_major_shape':['east_major_shape'],
        'east_hcp':['east_hcp'],
        'east_shape_and_hcp':['east_major_shape','east_hcp'],
        'west_spade_length':['west_spade_length'],
        'west_hcp':['west_hcp'],
    }
    partitions = {name:partition(rows,fields,len(rows)) for name,fields in specs.items()}
    ace = [('heart_ace',lambda r:r['has_heart_ace'])]
    adjusted = {}
    for name,fields in [
        ('ace_at_same_north_hcp_and_shape',['north_hcp','north_shape']),
        ('ace_at_same_north_hcp_shape_spade_hcp',['north_hcp','north_shape','north_spade_hcp']),
    ]:
        adjusted[name] = {outcome:adjusted_fit(rows,ace,fields,outcome)
                          for outcome in ['delta_imp','loss8']}
    same_four = [r for r in rows if r['heart_honors'] in ('A','KJ')]
    adjusted['A_only_versus_KJ_same_four_heart_hcp'] = {
        outcome:adjusted_fit(same_four,ace,['north_hcp','north_shape'],outcome)
        for outcome in ['delta_imp','loss8']}
    categories=['J_only','Q_or_QJ','K_or_KJ','KQ_or_KQJ','A_present']
    indicators=[(c,lambda r,c=c:int(r['heart_category']==c)) for c in categories]
    adjusted['heart_categories_vs_no_honors_fixed_north_hcp_shape'] = {
        outcome:adjusted_fit(rows,indicators,['north_hcp','north_shape'],outcome)
        for outcome in ['delta_imp','loss8']}
    report = dict(n=len(rows),overall=summarize(rows,len(rows)),partitions=partitions,
                  adjusted_associations=adjusted,
                  interpretation='Post-hoc hidden-hand associations, not observable decision rules or causal effects. Intervals describe conditional Monte Carlo sampling uncertainty only. Subgroup comparisons are exploratory and not corrected for multiplicity.',
                  structural_cautions=[
                      'North heart length is coupled to minor fit and East heart length; it is not an isolated intervention.',
                      'North HCP + East HCP + West HCP = 29, so HCP effects cannot be interpreted independently.',
                      'West initial Pass and preference rules couple spade support with its HCP range.',
                      'The fixed-effects adjustment conditions on North total HCP and shape but does not remove all relationships induced by the auction model.',
                  ],
                  source_sha256={name:sha256((run/name).read_bytes()).hexdigest()
                                 for name in ('deals.json','results.jsonl')},
                  no_dds_or_par_recomputed=True)
    output.mkdir(parents=True,exist_ok=True)
    (output/'factors.json').write_text(json.dumps(report,indent=2)+'\n')
    csvrows=[]
    for factor,groups in partitions.items():
        for group,stats in groups.items():
            flat={k:v for k,v in stats.items() if k != 'mean_imp_normal95'}
            flat.update(factor=factor,group=group,
                        mean_imp_ci_low=(stats['mean_imp_normal95'] or [None,None])[0],
                        mean_imp_ci_high=(stats['mean_imp_normal95'] or [None,None])[1])
            csvrows.append(flat)
    with (output/'factors.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(csvrows[0]));writer.writeheader();writer.writerows(csvrows)
    print(json.dumps({name:partitions[name] for name in ['north_heart_length','north_heart_category','north_best_minor_fit']},indent=2))
    print(json.dumps(adjusted,indent=2))


if __name__ == '__main__':
    main()
