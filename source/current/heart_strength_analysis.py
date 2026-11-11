"""Exploratory association of North's hearts with paired Double-minus-Pass.

Uses existing outcomes only. Excludes exactly East 7S4H (model v3); no new
club-response exclusions, deal generation, DDS, or Par calculations.
"""
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

import numpy as np
from scipy.stats import norm, t

ROOT = Path(__file__).parent
HCP = dict(A=4, K=3, Q=2, J=1)


def wilson(k, n):
    z = norm.ppf(.975)
    p = k/n
    den = 1 + z*z/n
    center = (p+z*z/(2*n))/den
    half = z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [float(center-half), float(center+half)]


def summarize(rows):
    y = np.array([r['delta_imp'] for r in rows], float)
    n = len(y)
    mean = float(y.mean())
    sem = float(y.std(ddof=1)/np.sqrt(n)) if n>1 else None
    margin = float(t.ppf(.975,n-1)*sem) if n>1 else None
    loss8 = int((y<=-8).sum())
    return dict(n=n, mean_imp=mean,
        mean_imp_t95=[mean-margin,mean+margin] if margin is not None else None,
        loss8_count=loss8, loss8_rate=loss8/n, loss8_wilson95=wilson(loss8,n),
        loss10_count=int((y<=-10).sum()), loss10_rate=float((y<=-10).mean()),
        bam_mean=float(np.mean([r['bam_points'] for r in rows])),
        mean_north_hcp=float(np.mean([r['north_hcp'] for r in rows])))


def partition(rows, key):
    groups=defaultdict(list)
    for row in rows: groups[str(row[key])].append(row)
    return {name:summarize(group) for name,group in sorted(groups.items())}


def fixed_effects(rows, features, strata_fields, outcome):
    """OLS after demeaning within exact strata; HC3 includes FE leverage.

    Estimates associations at fixed total HCP/shape, not causal effects.
    Uses no DD tricks or final contract as explanatory variables.
    """
    n=len(rows)
    X=np.array([[f(r) for name,f in features] for r in rows],float)
    y=np.array([r[outcome] for r in rows],float)
    Xw=X.copy(); yw=y.copy()
    groups=defaultdict(list)
    for i,r in enumerate(rows): groups[tuple(r[f] for f in strata_fields)].append(i)
    fe_leverage=np.zeros(n)
    for indices in groups.values():
        Xw[indices]-=X[indices].mean(axis=0)
        yw[indices]-=y[indices].mean()
        fe_leverage[indices]=1/len(indices)
    bread=np.linalg.inv(Xw.T@Xw)
    coefficients=bread@(Xw.T@yw)
    residual=yw-Xw@coefficients
    leverage=fe_leverage+np.einsum('ij,jk,ik->i',Xw,bread,Xw)
    # Singleton strata contribute zero demeaned design and no slope information.
    scale=np.divide(residual,1-leverage,out=np.zeros_like(residual),where=(1-leverage)>1e-10)**2
    covariance=bread@(Xw.T@(Xw*scale[:,None]))@bread
    se=np.sqrt(np.maximum(0,np.diag(covariance)))
    return dict(n=n, strata=len(groups), strata_fields=strata_fields, outcome=outcome,
        estimator='within-stratum OLS with HC3 heteroskedastic robust intervals',
        coefficients={name:dict(estimate=float(b),se_hc3=float(s),
            ci95=[float(b-1.959963984540054*s),float(b+1.959963984540054*s)])
            for (name,_),b,s in zip(features,coefficients,se)})


def main():
    p=ROOT/'run_10000'
    deals=json.loads((p/'deals.json').read_text())['deals']
    results={r['number']:r for r in map(json.loads,(p/'results.jsonl').read_text().splitlines())}
    rows=[]
    for d in deals:
        if d['hands']['E']['shape_SHDC'][:2]==[7,4]:continue
        n=d['hands']['N']; h=n['suits']['H']; s=n['suits']['S']; r=results[d['number']]
        honors=''.join(c for c in 'AKQJ' if c in h) or '-'
        if 'A' in h: category='A_present'
        elif 'K' in h and 'Q' in h: category='KQ_or_KQJ'
        elif 'K' in h: category='K_or_KJ'
        elif 'Q' in h: category='Q_or_QJ'
        elif 'J' in h: category='J_only'
        else:category='no_AKQJ'
        rows.append(dict(number=d['number'],hearts=h,heart_honors=honors,
            heart_category=category,has_heart_ace=int('A' in h),heart_length=len(h),
            heart_hcp=sum(HCP.get(c,0) for c in h),north_hcp=n['hcp'],
            north_spade_length=len(s),north_spade_hcp=sum(HCP.get(c,0) for c in s),
            north_shape='-'.join(map(str,n['shape_SHDC'])),
            delta_imp=r['delta_imp'], loss8=int(r['delta_imp']<=-8),
            loss10=int(r['delta_imp']<=-10),bam_points=r['bam_points'],
            pass_score_ns=r['pass_score_ns'],par_score_ns=r['double_par_score_ns'],
            handviewer_url=r['handviewer_url']))
    assert len(rows)==9804 and sum(r['delta_imp'] for r in rows)==-1875
    summary=dict(n=len(rows), definition='delta IMP is Double minus Pass; large loss means delta <= -8 IMP',
        cohort='Existing model-v3 9804 deals, exclude exact East 7S4H only; club rules unchanged',
        interpretation='Exploratory associations; intervals cover simulation sampling uncertainty, not model error or causal effects.',
        overall=summarize(rows),
        by_heart_honors=partition(rows,'heart_honors'),
        by_heart_category=partition(rows,'heart_category'),
        by_heart_hcp=partition(rows,'heart_hcp'),
        by_heart_length=partition(rows,'heart_length'),
        by_heart_ace=partition(rows,'has_heart_ace'))
    summary['heart_category_by_length']={str(length):partition([r for r in rows if r['heart_length']==length],'heart_category') for length in [2,3]}
    summary['adjusted']={}
    ace=[('heart_ace',lambda r:r['has_heart_ace'])]
    strata=['north_hcp','heart_length','north_spade_length']
    for label,fields in [('hcp_and_major_lengths',strata),('hcp_and_full_shape',['north_hcp','north_shape']),
                         ('plus_spade_hcp',strata+['north_spade_hcp'])]:
        summary['adjusted'][label]={outcome:fixed_effects(rows,ace,fields,outcome) for outcome in ['delta_imp','loss8']}
    same_four=[r for r in rows if r['heart_honors'] in ['A','KJ']]
    summary['adjusted']['A_only_versus_KJ_same_4HCP']={outcome:fixed_effects(same_four,ace,['north_hcp','north_shape'],outcome) for outcome in ['delta_imp','loss8']}
    cats=['J_only','Q_or_QJ','K_or_KJ','KQ_or_KQJ','A_present']
    features=[(c,lambda r,c=c:int(r['heart_category']==c)) for c in cats]
    summary['adjusted']['categories_vs_no_honors']={outcome:fixed_effects(rows,features,['north_hcp','north_shape'],outcome) for outcome in ['delta_imp','loss8']}
    output=ROOT/'heart_strength_review';output.mkdir(exist_ok=True)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    with (output/'deals.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    with (output/'groups.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['heart_honors','n','mean_delta_IMP','mean_CI_low','mean_CI_high','loss8_rate','loss8_CI_low','loss8_CI_high'])
        for name,g in summary['by_heart_honors'].items():
            writer.writerow([name,g['n'],g['mean_imp'],*(g['mean_imp_t95'] or [None,None]),g['loss8_rate'],*g['loss8_wilson95']])
    print(json.dumps({k:summary[k] for k in ['by_heart_category','adjusted']},indent=2))


if __name__=='__main__': main()
