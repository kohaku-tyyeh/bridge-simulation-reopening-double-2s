#!/usr/bin/env python3
"""Re-solve saved DK deals with selected NS level-three suit doubles prohibited."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
import time

import numpy as np

from analyze_dk_contracts import component, label
from continuation_par_policy import solve
from test_continuation_par import oracle_score

THRESHOLDS = [20, 50, 90, 130, 170, 220, 270, 320, 370, 430, 500, 600,
              750, 900, 1100, 1300, 1500, 1750, 2000, 2250, 2500, 3000, 3500, 4000]


def imps(delta):
    return (1 if delta >= 0 else -1) * bisect_right(THRESHOLDS, abs(delta))


def mask_for(deal, allow_41):
    mask = 0
    for i, suit in enumerate('CDHS'):
        lengths = {s: len(deal['hands'][s]['suits'][suit]) for s in 'NESW'}
        if lengths['N'] + lengths['S'] == 8:
            split = sorted((lengths['E'], lengths['W']))
            if split == [2, 3] or allow_41 and split == [1, 4]:
                mask |= 1 << i
    return mask


def forbidden(c, mask):
    return (c['declarer'] in 'NS' and c['level'] == 3 and c['doubled'] > 0
            and bool(mask & (1 << 'CDHSN'.index(c['strain']))))


def stats(rows):
    n = len(rows)
    return dict(n=n, mean_imp=sum(r['delta_imp'] for r in rows)/n,
                sum_imp=sum(r['delta_imp'] for r in rows),
                bam_mean_points=sum(r['bam_points'] for r in rows)/n,
                bam_counts=dict(win=sum(r['delta_ns']>0 for r in rows),
                                tie=sum(r['delta_ns']==0 for r in rows),
                                loss=sum(r['delta_ns']<0 for r in rows)),
                mean_double_par_score=sum(r['double_par_score_ns'] for r in rows)/n,
                mean_pass_score=sum(r['pass_score_ns'] for r in rows)/n,
                mean_raw_delta=sum(r['delta_ns'] for r in rows)/n,
                imp_positive=sum(r['delta_imp']>0 for r in rows),
                imp_zero=sum(r['delta_imp']==0 for r in rows),
                imp_negative=sum(r['delta_imp']<0 for r in rows),
                loss8=sum(r['delta_imp']<=-8 for r in rows),
                loss10=sum(r['delta_imp']<=-10 for r in rows),
                gain8=sum(r['delta_imp']>=8 for r in rows),
                imp_distribution=dict(sorted(Counter(r['delta_imp'] for r in rows).items())),
                par_score_distribution=dict(sorted(Counter(r['double_par_score_ns'] for r in rows).items())))


def paired(old, new):
    n = len(old)
    return dict(n=n, par_score_improved=sum(a['double_par_score_ns']<b['double_par_score_ns'] for a,b in zip(old,new)),
                imp_diff_improved=sum(a['delta_imp']<b['delta_imp'] for a,b in zip(old,new)),
                bam_improved=sum(a['bam_points']<b['bam_points'] for a,b in zip(old,new)),
                mean_imp_diff_increase=sum(b['delta_imp']-a['delta_imp'] for a,b in zip(old,new))/n,
                bam_increase=sum(b['bam_points']-a['bam_points'] for a,b in zip(old,new))/n,
                mean_par_score_increase=sum(b['double_par_score_ns']-a['double_par_score_ns'] for a,b in zip(old,new))/n,
                rescued_loss8=sum(a['delta_imp']<=-8 and b['delta_imp']>-8 for a,b in zip(old,new)),
                rescued_loss10=sum(a['delta_imp']<=-10 and b['delta_imp']>-10 for a,b in zip(old,new)),
                raw_outcome_transitions=dict(Counter(
                    ('win' if a['delta_ns']>0 else 'loss' if a['delta_ns']<0 else 'tie')+' -> '+
                    ('win' if b['delta_ns']>0 else 'loss' if b['delta_ns']<0 else 'tie') for a,b in zip(old,new))))


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def bootstrap(models, replicates, seed):
    n=len(models[0])
    imp=np.array([[r['delta_imp'] for r in rs] for rs in models], dtype=float)
    bam=np.array([[r['bam_points'] for r in rs] for rs in models], dtype=float)
    rng=np.random.default_rng(seed)
    values=np.empty((replicates, 6))
    for start in range(0,replicates,100):
        end=min(replicates,start+100)
        indices=rng.integers(0,n,size=(end-start,n),dtype=np.int32)
        for m in range(3):
            values[start:end,m]=imp[m][indices].mean(axis=1)
            values[start:end,m+3]=bam[m][indices].mean(axis=1)
    answer={}
    for name, idx in [('original',0),('protect_32',1),('protect_32_41',2)]:
        answer[name]=dict(mean_imp_95=np.quantile(values[:,idx],[.025,.975]).tolist(),
                          bam_mean_95=np.quantile(values[:,idx+3],[.025,.975]).tolist())
    for name,l,r in [('protect_32_minus_original',0,1),('protect_32_41_minus_original',0,2),
                     ('protect_32_41_minus_protect_32',1,2)]:
        answer[name]=dict(mean_imp_diff_increase_95=np.quantile(values[:,r]-values[:,l],[.025,.975]).tolist(),
                         bam_increase_95=np.quantile(values[:,r+3]-values[:,l+3],[.025,.975]).tolist())
    return dict(replicates=replicates,seed=seed,paired_same_deals=True,intervals=answer)


def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir',nargs='?',type=Path,default=root/'run_v5_10000')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--bootstrap',type=int,default=10000)
    args=parser.parse_args()
    run=args.run_dir; out=args.output or run/'no_double_policy'
    out.mkdir(exist_ok=True)
    deals=json.loads((run/'deals.json').read_text())['deals']
    original=[json.loads(s) for s in (run/'results.jsonl').read_text().splitlines()]
    dds=[json.loads(s) for s in (run/'dds.jsonl').read_text().splitlines()]
    assert len(deals)==len(original)==len(dds)>0
    original_summary=json.loads((run/'summary.json').read_text())
    assert len(original)==original_summary['n']
    assert abs(sum(r['delta_imp'] for r in original)/len(original)
               - original_summary['mean_imp']) < 1e-12
    source_hashes={name:sha256((run/name).read_bytes()).hexdigest()
                   for name in ['deals.json','results.jsonl','dds.jsonl','summary.json']}
    models={'protect_32':[], 'protect_32_41':[]}
    mask_counts={k:Counter() for k in models}
    coverage={k:Counter() for k in models}
    started=time.monotonic()
    for model,allow_41 in [('protect_32',False),('protect_32_41',True)]:
        with (out/f'{model}.jsonl').open('w',buffering=1) as f:
            for d,r,dd in zip(deals,original,dds):
                assert d['number']==r['number']==dd['number']
                assert dd['pbn']==r['pbn'] and r['pbn'].split()[2]=='3.9754.AKT8.A764'
                mask=mask_for(d,allow_41);mask_counts[model][mask]+=1
                for i,suit in enumerate('CDHS'):
                    coverage[model][suit]+=bool(mask & (1<<i))
                table=dd['dd_table_CDHSN_NESW']
                par=solve(table,blocked_ns_level3_strains=mask,want_pv=True,want_all=True)
                assert par['optimal_contracts']
                assert par['score_ns']>=r['double_par_score_ns']
                for c in par['optimal_contracts']:
                    i='CDHSN'.index(c['strain']);seat='NESW'.index(c['declarer'])
                    assert oracle_score(c['level'],i,seat,table[i][seat],c['doubled'])==par['score_ns']
                    assert not forbidden(c,mask)
                if mask==0:
                    assert par['score_ns']==r['double_par_score_ns']
                    assert {label(c,True) for c in par['optimal_contracts']}=={label(c,True) for c in r['optimal_contracts']}
                delta=par['score_ns']-r['pass_score_ns']
                row=dict(number=r['number'],pbn=r['pbn'],handviewer_url=r['handviewer_url'],
                         east_2S_tricks=r['east_2S_tricks'],pass_score_ns=r['pass_score_ns'],
                         double_par_score_ns=par['score_ns'],delta_ns=delta,delta_imp=imps(delta),
                         bam_points=1 if delta>0 else 0 if delta<0 else .5,
                         optimal_contracts=par['optimal_contracts'],
                         representative_continuation=par['auction'],representative_contract=par['contract'],
                         blocked_ns_level3_strains=mask,original_par_score_ns=r['double_par_score_ns'],
                         original_delta_imp=r['delta_imp'],solver_seconds=par['seconds'])
                if model=='protect_32_41':
                    prior=models['protect_32'][len(models[model])]
                    assert row['double_par_score_ns']>=prior['double_par_score_ns']
                models[model].append(row);f.write(json.dumps(row)+'\n')
                if len(models[model])%1000==0:
                    print(f'{model} {len(models[model])}/{len(original)}; elapsed {time.monotonic()-started:.1f}s',flush=True)
    n=len(original)
    summary=dict(dataset=str(run),n=n,fixed_south='S3 H9754 DAKT8 CA764',
                 vulnerability='NS nonvulnerable; EW vulnerable',
                 definitions={
                     'protect_32':'Prohibit EW double of NS level-three suit contracts with exactly 8-card NS fit and EW 3-2 split.',
                     'protect_32_41':'Same, additionally protect EW 4-1 splits; EW 5-0 remains unprotected.',
                     'scope':'Both NS declarers, all four suit strains, throughout the continuation auction. No effect on 3NT or other levels; NS doubling EW unchanged.',
                     'method':'Re-solve exact history-constrained minimax after South doubles East 2S, West next; saved deals and DDS tables reused.',
                     'impact':'Change in mean per-deal IMP(Double Par minus Pass), not IMP applied to a mean score or to the correction itself.',
                 },original=stats(original),
                 scenarios={k:stats(v) for k,v in models.items()},
                 comparisons={k+'_minus_original':paired(original,v) for k,v in models.items()},
                 mask_counts={k:dict(v) for k,v in mask_counts.items()},
                 suit_coverage={k:dict(v) for k,v in coverage.items()},
                 source_sha256=source_hashes,no_deals_or_dds_recomputed=True)
    summary['comparisons']['protect_32_41_minus_protect_32']=paired(models['protect_32'],models['protect_32_41'])
    summary['bootstrap']=bootstrap([original,*models.values()],args.bootstrap,2026111107)
    summary['elapsed_seconds']=time.monotonic()-started
    summary['source_code_sha256']={name:sha256((root/name).read_bytes()).hexdigest()
        for name in ['run_dk_no_double_policy.py','continuation_par_policy.cpp','continuation_par_policy.py']}
    board_rows=[];grouped=defaultdict(list)
    for d,r,dd,a,b in zip(deals,original,dds,*models.values()):
        oldcat=component(r,dd['dd_table_CDHSN_NESW'])
        row=dict(number=r['number'],original_component=oldcat,pass_score_ns=r['pass_score_ns'],
                 original_par=r['double_par_score_ns'],original_imp=r['delta_imp'],original_bam=r['bam_points'],
                 protect_32_par=a['double_par_score_ns'],protect_32_imp=a['delta_imp'],protect_32_bam=a['bam_points'],
                 protect_32_41_par=b['double_par_score_ns'],protect_32_41_imp=b['delta_imp'],protect_32_41_bam=b['bam_points'],
                 mask_32=a['blocked_ns_level3_strains'],mask_32_41=b['blocked_ns_level3_strains'],
                 old_optimal_contains_forbidden_32=any(forbidden(c,a['blocked_ns_level3_strains']) for c in r['optimal_contracts']),
                 old_optimal_contains_forbidden_32_41=any(forbidden(c,b['blocked_ns_level3_strains']) for c in r['optimal_contracts']),
                 old_contracts='; '.join(sorted({label(c,True) for c in r['optimal_contracts']})),
                 contracts_32='; '.join(sorted({label(c,True) for c in a['optimal_contracts']})),
                 contracts_32_41='; '.join(sorted({label(c,True) for c in b['optimal_contracts']})),
                 handviewer_url=r['handviewer_url'])
        board_rows.append(row);grouped[oldcat].append((r,a,b))
    contributions=[]
    for k,rs in grouped.items():
        contributions.append(dict(original_component=k,n=len(rs),
             original_mean_contribution=sum(r[0]['delta_imp'] for r in rs)/n,
             protect_32_mean_contribution=sum(r[1]['delta_imp'] for r in rs)/n,
             protect_32_41_mean_contribution=sum(r[2]['delta_imp'] for r in rs)/n,
             protect_32_increase=sum(r[1]['delta_imp']-r[0]['delta_imp'] for r in rs)/n,
             protect_32_41_increase=sum(r[2]['delta_imp']-r[0]['delta_imp'] for r in rs)/n))
    summary['contributions_by_original_component']=contributions
    summary['strategic_changes']={k:dict(
         old_optimal_forbidden=sum(row['old_optimal_contains_forbidden_'+suffix] for row in board_rows),
         improved_without_old_forbidden_terminal=sum(
             not row['old_optimal_contains_forbidden_'+suffix] and row[k+'_par']>row['original_par'] for row in board_rows))
         for k,suffix in [('protect_32','32'),('protect_32_41','32_41')]}
    for name,digest in source_hashes.items():assert sha256((run/name).read_bytes()).hexdigest()==digest
    write_csv(out/'paired_comparison.csv',board_rows)
    write_csv(out/'contributions_by_original_component.csv',contributions)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['original','scenarios','comparisons','strategic_changes']},indent=2),flush=True)


if __name__=='__main__':
    main()
