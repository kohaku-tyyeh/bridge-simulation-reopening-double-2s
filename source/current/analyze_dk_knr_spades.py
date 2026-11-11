#!/usr/bin/env python3
"""Rank North's five spades by the suit's full Kaplan-Rubens contribution.

Formula: Richard Pavlicek's 26-step interpretation, https://www.rpbridge.net/8j19.htm
For length five, no shortness or 7+-card terms apply. The whole-hand -1 and
4333 adjustment are not allocated to this suit. Keep the separate suit-quality
term to disambiguate it from the full suit contribution.
"""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


def knr_five(cards):
    assert len(cards) == len(set(cards)) == 5 and set(cards) <= set('AKQJT98765432')
    h=set(cards)
    # Twice the unscaled quality points. All five-card outputs are quarter points.
    quality_twice=sum({'A':8,'K':6,'Q':4,'J':2,'T':1}.get(c,0) for c in h)
    if 'T' in h and ('J' in h or len(h & set('AKQJ')) >= 2):
        quality_twice += 1
    if '9' in h and ('8' in h or 'T' in h or len(h & set('AKQJT')) == 2):
        quality_twice += 1
    if '9' in h and '8' not in h and 'T' not in h and len(h & set('AKQJ')) == 3:
        quality_twice += 1
    quality=quality_twice / 4  # length/10 = 1/2, on half-point units
    control_quarters=12*('A' in h)+8*('K' in h)
    if 'Q' in h:
        control_quarters += 4 if ('A' in h or 'K' in h) else 3
    if 'J' in h:
        higher=len(h & set('AKQ'))
        control_quarters += 2 if higher == 2 else 1 if higher == 1 else 0
    if 'T' in h:
        higher=len(h & set('AKQJ'))
        control_quarters += int(higher == 2)
        control_quarters += int('9' in h and higher == 1)
    control=control_quarters / 4
    return dict(knr_suit_points=quality+control,quality_component=quality,
                control_component=control)


def cohort_summary(rows, field='knr_suit_points'):
    n=len(rows);m=median(r[field] for r in rows)
    below=sum(r[field]<m for r in rows);equal=sum(r[field]==m for r in rows)
    ordered=sorted(rows,key=lambda r:(r[field],r['number']))
    centers=[n//2] if n%2 else [n//2-1,n//2]
    return dict(n=n,median=m,below=below,equal=equal,above=n-below-equal,
                median_tie_rank_first=below+1,median_tie_rank_last=below+equal,
                middle_records=[{k:ordered[i][k] for k in ['number','north_spades',field]} for i in centers],
                median_holding_frequencies=dict(Counter(r['north_spades'] for r in rows if r[field]==m).most_common()),
                frequency=[dict(points=x,n=k) for x,k in sorted(Counter(r[field] for r in rows).items())])


def write_ranked(path, rows, field='knr_suit_points'):
    counts=Counter(r[field] for r in rows);ranks={};first=1
    for value,count in sorted(counts.items()):
        ranks[value]=(first,first+count-1);first+=count
    output=[]
    for i,r in enumerate(sorted(rows,key=lambda r:(r[field],r['number'])),1):
        output.append(dict(sorted_row=i,tied_rank_first=ranks[r[field]][0],
                           tied_rank_last=ranks[r[field]][1],**r))
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run_dir',nargs='?',type=Path,default=Path(__file__).resolve().parent/'run_v5_10000')
    args=ap.parse_args();run=args.run_dir
    out=run/'no_double_policy/knr_spades';out.mkdir(exist_ok=True)
    deal_path=run/'deals.json';result_path=run/'no_double_policy/protect_32_41.jsonl'
    deals=json.loads(deal_path.read_text())['deals']
    results={r['number']:r for r in map(json.loads,result_path.read_text().splitlines())}
    target=dict(level=2,strain='S',declarer='E',doubled=1)
    rows=[]
    for d in deals:
        north=d['hands']['N'];s=north['suits']['S']
        if len(s)!=5:continue
        r=results[d['number']]
        eligible=target in r['optimal_contracts']
        link=r['handviewer_url']
        if eligible:
            u=urlsplit(link);q=parse_qs(u.query)
            assert q['a']==['p1sdp1n2hp2spp']
            q['a']=['p1sdp1n2hp2sppdppp']
            link=urlunsplit((u.scheme,u.netloc,u.path,urlencode(q,doseq=True),u.fragment))
        rows.append(dict(number=d['number'],north_spades=s,**knr_five(s),
                         north_hearts=north['suits']['H'],north_diamonds=north['suits']['D'],
                         north_clubs=north['suits']['C'],north_hcp=north['hcp'],
                         two_sx_is_optimal=eligible,two_sx_is_unique=eligible and len(r['optimal_contracts'])==1,
                         east_2S_tricks=r['east_2S_tricks'],par_score_ns=r['double_par_score_ns'],
                         delta_imp=r['delta_imp'],handviewer_url=link))
    cohorts=dict(all_five_spades=rows,
                 two_sx_optimal=[r for r in rows if r['two_sx_is_optimal']],
                 two_sx_unique=[r for r in rows if r['two_sx_is_unique']])
    assert [len(v) for v in cohorts.values()]==[2046,1047,360]
    summaries={k:dict(full_suit=cohort_summary(v),quality_only=cohort_summary(v,'quality_component'))
               for k,v in cohorts.items()}
    principal=cohorts['two_sx_optimal']
    quoted=next(r for r in principal if r['number']==3)
    lower=sum(r['knr_suit_points']<quoted['knr_suit_points'] for r in principal)
    equal=sum(r['knr_suit_points']==quoted['knr_suit_points'] for r in principal)
    report=dict(dataset='Latest DK, protect_32_41 continuation-Par policy',
                main_cohort='North exactly five spades, East 2SX among cooptimal terminals; each saved deal equally weighted.',
                scoring='Full single-suit Kaplan-Rubens contribution = quality component + protected high-card/lower-honor component. No other suits or whole-hand adjustments.',
                formula_source='https://www.rpbridge.net/8j19.htm',
                supplemental_source='https://www.jeff-goldsmith.com/knr.txt',
                cohorts=summaries,
                quoted_QT764=dict(**quoted,below=lower,equal=equal,above=len(principal)-lower-equal,
                                  tied_rank_first=lower+1,tied_rank_last=lower+equal,
                                  mid_distribution_percentile=(lower+equal/2)/len(principal)*100),
                no_deals_dds_or_par_recomputed=True,
                source_sha256={str(p.relative_to(run)):sha256(p.read_bytes()).hexdigest()
                               for p in [deal_path,result_path]},
                script_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
    for k,v in cohorts.items():write_ranked(out/(k+'_ranked.csv'),v)
    write_ranked(out/'two_sx_optimal_quality_only_ranked.csv',principal,'quality_component')
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    for k,s in summaries.items():
        print(k,{field:{a:v for a,v in stats.items() if a not in ['median_holding_frequencies','frequency']}
                 for field,stats in s.items()})
    print('quoted_QT764',report['quoted_QT764'])


if __name__=='__main__':
    main()
