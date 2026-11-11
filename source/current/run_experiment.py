"""Paired Pass versus post-Double continuation Par experiment.

Run with the project .venv Python. All outcomes are NS scores. Full DD tables
are saved separately and reusable. No filtering uses outcomes.
"""
import argparse
from bisect import bisect_right
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import platform
import time

import numpy as np

from continuation_par import solve, score
from dds_backend import generate_cache, pbn

IMP_THRESHOLDS = [20,50,90,130,170,220,270,320,370,430,500,600,
                  750,900,1100,1300,1500,1750,2000,2250,2500,3000,3500,4000]


def imps(delta):
    return (1 if delta >= 0 else -1) * bisect_right(IMP_THRESHOLDS, abs(delta))


def contract_label(contract):
    return (str(contract['level']) + contract['strain']
            + ['', 'X', 'XX'][contract['doubled']] + ' ' + contract['declarer'])


def contract_score(contract, table):
    strain = 'CDHSN'.index(contract['strain'])
    seat = 'NESW'.index(contract['declarer'])
    return (1 if seat % 2 == 0 else -1) * score(
        contract['level'], strain, table[strain][seat],
        contract['doubled'], seat % 2 == 1)


def wilson(count, total):
    z = 1.959963984540054
    p = count / total
    denominator = 1 + z*z / total
    center = (p + z*z/(2*total))/denominator
    radius = z * np.sqrt(p*(1-p)/total + z*z/(4*total*total))/denominator
    return [float(center-radius), float(center+radius)]


def statistics(rows, bootstrap_count=10000, bootstrap_seed=20261111):
    delta = np.array([r['delta_ns'] for r in rows], dtype=float)
    imp = np.array([r['delta_imp'] for r in rows], dtype=float)
    bam = np.where(delta > 0, 1., np.where(delta == 0, .5, 0.))
    n = len(rows)
    rng = np.random.default_rng(bootstrap_seed)
    boot = np.empty((bootstrap_count, 3))
    for i in range(0, bootstrap_count, 200):
        end = min(i+200, bootstrap_count)
        indices = rng.integers(0, n, size=(end-i, n), dtype=np.int32)
        boot[i:end, 0] = imp[indices].mean(axis=1)
        boot[i:end, 1] = bam[indices].mean(axis=1)
        boot[i:end, 2] = delta[indices].mean(axis=1)
    ci = np.quantile(boot, [.025, .975], axis=0)
    count = {key: int(np.count_nonzero(mask)) for key, mask in
             [('win', delta>0), ('tie', delta==0), ('loss', delta<0)]}
    contracts = Counter()
    for row in rows:
        contracts.update(set(contract_label(c) for c in row['optimal_contracts']))
    grouped = []
    for tricks in sorted(set(r['east_2S_tricks'] for r in rows)):
        group = [r for r in rows if r['east_2S_tricks'] == tricks]
        grouped.append(dict(east_2S_tricks=tricks, count=len(group),
            wins=sum(r['delta_ns']>0 for r in group),
            ties=sum(r['delta_ns']==0 for r in group),
            losses=sum(r['delta_ns']<0 for r in group),
            mean_imp=float(np.mean([r['delta_imp'] for r in group]))))
    best = sorted(rows, key=lambda r:(-r['delta_imp'], -r['delta_ns'], r['number']))[:3]
    worst = sorted(rows, key=lambda r:(r['delta_imp'], r['delta_ns'], r['number']))[:3]
    return dict(
        n=n, positive_means='Double better than Pass, NS viewpoint',
        bam_counts=count,
        bam_proportions={k:v/n for k,v in count.items()},
        bam_proportion_wilson_95={k:wilson(v,n) for k,v in count.items()},
        bam_mean_points=float(bam.mean()), bam_mean_points_bootstrap_95=ci[:,1].tolist(),
        bam_net_win_proportion=(count['win']-count['loss'])/n,
        mean_imp=float(imp.mean()), mean_imp_bootstrap_95=ci[:,0].tolist(),
        mean_raw_delta=float(delta.mean()), mean_raw_delta_bootstrap_95=ci[:,2].tolist(),
        mean_pass_score=float(np.mean([r['pass_score_ns'] for r in rows])),
        mean_double_par_score=float(np.mean([r['double_par_score_ns'] for r in rows])),
        imp_distribution=dict(sorted(Counter(map(int,imp)).items())),
        double_par_score_distribution=dict(sorted(Counter(r['double_par_score_ns'] for r in rows).items())),
        raw_delta_quantiles=dict(zip(['min','p01','p05','median','p95','p99','max'],
                                    np.quantile(delta,[0,.01,.05,.5,.95,.99,1]).tolist())),
        multiple_optimal_contract_deals=sum(len(r['optimal_contracts'])>1 for r in rows),
        optimal_contract_occurrences=[dict(contract=c,count=k,proportion=k/n)
                                      for c,k in contracts.most_common()],
        optimal_contract_frequency_note='Counts indicate presence among co-optimal terminal contracts; categories can overlap and need not sum to n.',
        grouped_by_undoubled_2S_tricks=grouped,
        representative_best=best, representative_worst=worst,
        bootstrap_replicates=bootstrap_count, bootstrap_seed=bootstrap_seed,
        inference_note='Intervals quantify conditional Monte Carlo sampling uncertainty, not bidding-model error or perfect-information Par approximation error.',
        imp_note='Convert each paired action score difference to IMPs before averaging; no field or other-table datum is assumed.',
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--dds-threads', type=int, default=3)
    parser.add_argument('--bootstrap-count', type=int, default=10000)
    args = parser.parse_args()
    directory = args.run_dir
    dataset = json.loads((directory/'deals.json').read_text())
    records = dataset['deals']
    generate_cache(directory/'deals.json', directory/'dds.jsonl', args.dds_threads)
    tables = [json.loads(line) for line in (directory/'dds.jsonl').read_text().splitlines()]
    assert len(records) == len(tables)
    results = []
    started = time.monotonic()
    with (directory/'results.jsonl').open('w', buffering=1) as f:
        for record, dds in zip(records, tables):
            assert pbn(record) == dds['pbn'] and record['number'] == dds['number']
            table = dds['dd_table_CDHSN_NESW']
            par = solve(table, want_pv=True, want_all=True)
            baseline = -score(2, 3, table[3][1], 0, True)
            contracts = par['optimal_contracts']
            assert contracts
            assert contract_score(par['contract'], table) == par['score_ns']
            assert all(contract_score(c, table) == par['score_ns'] for c in contracts)
            difference = par['score_ns'] - baseline
            row = dict(number=record['number'], pbn=dds['pbn'],
                handviewer_url=record['handviewer_url'],
                east_2S_tricks=table[3][1],
                pass_score_ns=baseline, double_par_score_ns=par['score_ns'],
                delta_ns=difference, delta_imp=imps(difference),
                bam_points=1 if difference>0 else 0 if difference<0 else .5,
                optimal_contracts=contracts, representative_continuation=par['auction'],
                representative_contract=par['contract'],
                solver_nodes=par['nodes'], solver_seconds=par['seconds'])
            results.append(row)
            f.write(json.dumps(row)+'\n')
            if len(results)%1000==0:
                print(f'Continuation Par {len(results)}/{len(records)}; {time.monotonic()-started:.1f}s',flush=True)
    with (directory/'results.csv').open('w', newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['deal','east_2S_tricks','pass_NS','double_par_NS','delta_NS',
                         'delta_IMP','BAM_points','all_optimal_contracts','handviewer_url'])
        for r in results:
            writer.writerow([r['number'],r['east_2S_tricks'],r['pass_score_ns'],
                r['double_par_score_ns'],r['delta_ns'],r['delta_imp'],r['bam_points'],
                '; '.join(contract_label(c) for c in r['optimal_contracts']),r['handviewer_url']])
    summary = statistics(results, args.bootstrap_count)
    summary.update(seed=dataset['seed'], generated_deals=dataset['attempts'],
        rules=dataset['rules'], vulnerability='NS nonvulnerable, EW vulnerable',
        fixed_auction_before_action=dataset['auction'],
        double_branch_initial_state='South X, then West to act; all four seats unrestricted',
        python_version=platform.python_version())
    root = Path(__file__).parent
    summary['source_sha256']={name:sha256((root/name).read_bytes()).hexdigest() for name in
        ['filter_deals.py','nt_choice.py','knr_suit.py','rules.json','dds_backend.py','continuation_par.cpp',
         'continuation_par.py','run_experiment.py']}
    (directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['n','bam_counts','bam_mean_points',
        'mean_imp','mean_imp_bootstrap_95','mean_raw_delta','multiple_optimal_contract_deals']},indent=2),flush=True)


if __name__ == '__main__':
    main()
