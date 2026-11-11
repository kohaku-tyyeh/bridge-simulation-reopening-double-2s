#!/usr/bin/env python3
"""Cross-tabulate North's hearts with saved Par components; no new DDS/Par."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path

from analyze_dk_contracts import component, label
from analyze_dk_factors import heart_category

COMPONENTS = ['NS_down', 'NS_making', 'EW_2SX_available',
              'EW_making_partscore', 'EW_making_game', 'EW_other_down',
              'mixed_NS_making_or_EW_down']
COMMON_NS = {'NS 2NTX', 'NS 3CX', 'NS 3DX'}


def summarize(rows, all_n):
    n = len(rows)
    parts = []
    for name in COMPONENTS:
        subset = [r for r in rows if r['component'] == name]
        count = len(subset)
        total = sum(r['delta_imp'] for r in subset)
        large = sum(r['delta_imp'] <= -8 for r in subset)
        parts.append(dict(component=name, n=count, frequency_in_group=count/n,
                          sum_imp=total, mean_imp=total/count if count else None,
                          contribution_to_group_mean=total/n,
                          contribution_to_overall_mean=total/all_n,
                          loss8_count=large, loss8_rate_of_group=large/n))
    large = [r for r in rows if r['delta_imp'] <= -8]
    mechanisms = {
        'NS_down': sum(r['component'] == 'NS_down' for r in large),
        'EW_making_game': sum(r['component'] == 'EW_making_game' for r in large),
        'other': sum(r['component'] not in ('NS_down', 'EW_making_game') for r in large),
    }
    assert sum(mechanisms.values()) == len(large)
    assert sum(p['n'] for p in parts) == n
    assert sum(p['sum_imp'] for p in parts) == sum(r['delta_imp'] for r in rows)
    return dict(n=n, mean_imp=sum(r['delta_imp'] for r in rows)/n,
                loss8_count=len(large), loss8_rate=len(large)/n,
                large_loss_mechanisms={name:dict(
                    n=count, rate_of_group=count/n,
                    fraction_of_large_losses=count/len(large) if large else None)
                    for name,count in mechanisms.items()},
                ns_down_common_contract_union_n=sum(
                    r['component']=='NS_down' and bool(r['labels'] & COMMON_NS)
                    for r in rows),
                loss8_ns_down_common_contract_union_n=sum(
                    r['component']=='NS_down' and bool(r['labels'] & COMMON_NS)
                    for r in large),
                components=parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', nargs='?', type=Path,
                        default=Path(__file__).resolve().parent/'run_v5_10000')
    args = parser.parse_args()
    run = args.run_dir
    out = run/'contract_analysis'
    deals = json.loads((run/'deals.json').read_text())['deals']
    outcomes = {r['number']:r for r in map(json.loads,(run/'results.jsonl').read_text().splitlines())}
    dds = {r['number']:r for r in map(json.loads,(run/'dds.jsonl').read_text().splitlines())}
    rows = []
    groups = {'heart_length':defaultdict(list), 'heart_category':defaultdict(list),
              'heart_length_and_category':defaultdict(list)}
    for d in deals:
        r = outcomes[d['number']].copy()
        h = d['hands']['N']['suits']['H']
        assert r['pbn'] == dds[d['number']]['pbn']
        r['component'] = component(r,dds[d['number']]['dd_table_CDHSN_NESW'])
        r['labels'] = {label(c) for c in r['optimal_contracts']}
        rows.append(r)
        groups['heart_length'][str(len(h))].append(r)
        groups['heart_category'][heart_category(h)].append(r)
        groups['heart_length_and_category'][f'{len(h)}|{heart_category(h)}'].append(r)
    assert len(rows)==10000 and sum(r['delta_imp'] for r in rows)==4889
    summaries = {factor:{group:summarize(members,len(rows))
                        for group,members in sorted(grouped.items())}
                 for factor,grouped in groups.items()}
    for grouped in summaries.values():
        assert sum(g['n'] for g in grouped.values())==10000
        assert sum(sum(c['sum_imp'] for c in g['components']) for g in grouped.values())==4889
    short,long = (summaries['heart_length'][str(length)] for length in (2,3))
    differences = dict(
        direction='North 3 hearts minus North 2 hearts',
        mean_imp_difference=long['mean_imp']-short['mean_imp'],
        components=[dict(component=l['component'],
                         contribution_to_mean_difference=l['contribution_to_group_mean']-s['contribution_to_group_mean'])
                    for s,l in zip(short['components'],long['components'])],
        loss8_rate_difference=long['loss8_rate']-short['loss8_rate'],
        large_loss_mechanisms={k:
            long['large_loss_mechanisms'][k]['rate_of_group']-
            short['large_loss_mechanisms'][k]['rate_of_group']
            for k in short['large_loss_mechanisms']})
    assert abs(sum(c['contribution_to_mean_difference'] for c in differences['components'])-
               differences['mean_imp_difference'])<1e-10
    assert abs(sum(differences['large_loss_mechanisms'].values())-
               differences['loss8_rate_difference'])<1e-10
    report=dict(n=len(rows),overall=summarize(rows,len(rows)),groups=summaries,
                heart_length_difference= differences,
                loss8_definition='delta_imp <= -8, Double minus Pass',
                component_definition_source='analyze_dk_contracts.component',
                ns_down_common_contract_union_definition='At least one of NS 2NTX, NS 3CX, NS 3DX is among optimal contracts, and component=NS_down; each deal counted once.',
                interpretation='Descriptive, overlapping hand characteristics are not causal or observable bidding rules. Seven contract components are mutually exclusive; alternate equal-value optimal contracts are never counted as separate deals.',
                no_dds_or_par_recomputed=True)
    out.mkdir(exist_ok=True)
    (out/'heart_component_cross.json').write_text(json.dumps(report,indent=2)+'\n')
    csvrows=[]
    for factor,grouped in {'overall':{'all':report['overall']},**summaries}.items():
        for group,g in grouped.items():
            for c in g['components']:
                csvrows.append(dict(factor=factor,group=group,group_n=g['n'],
                                    group_mean_imp=g['mean_imp'],**c))
    with (out/'heart_component_cross.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(csvrows[0]));writer.writeheader();writer.writerows(csvrows)
    print(json.dumps({'overall':report['overall'], 'heart_length_difference':differences},indent=2))


if __name__=='__main__':
    main()
