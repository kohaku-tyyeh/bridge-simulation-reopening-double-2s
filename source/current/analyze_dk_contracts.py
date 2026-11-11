#!/usr/bin/env python3
"""Describe saved, auction-constrained DK continuation-Par outcomes; never rerun DDS."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path


def label(c, exact=False):
    strain = 'NT' if c['strain'] == 'N' else c['strain']
    seat = c['declarer'] if exact else ('NS' if c['declarer'] in 'NS' else 'EW')
    return f"{seat} {c['level']}{strain}{'X' * c['doubled']}"


def stats(rows, total):
    n = len(rows)
    imp = sum(r['delta_imp'] for r in rows)
    return dict(n=n, frequency=n / total, sum_imp=imp,
                mean_imp=imp / n if n else None,
                contribution_to_overall_mean=imp / total,
                raw_wins=sum(r['delta_ns'] > 0 for r in rows),
                raw_ties=sum(r['delta_ns'] == 0 for r in rows),
                raw_losses=sum(r['delta_ns'] < 0 for r in rows),
                bam_mean=sum(r['bam_points'] for r in rows) / n if n else None,
                loss8=sum(r['delta_imp'] <= -8 for r in rows),
                loss10=sum(r['delta_imp'] <= -10 for r in rows),
                gain8=sum(r['delta_imp'] >= 8 for r in rows),
                gain10=sum(r['delta_imp'] >= 10 for r in rows))


def component(row, table):
    contracts = row['optimal_contracts']
    sides = {'NS' if c['declarer'] in 'NS' else 'EW' for c in contracts}
    made = [table['CDHSN'.index(c['strain'])]['NESW'.index(c['declarer'])]
            >= 6 + c['level'] for c in contracts]
    if len(sides) == 2:
        assert row['double_par_score_ns'] > 0
        return 'mixed_NS_making_or_EW_down'
    assert len(set(made)) == 1
    if sides == {'NS'}:
        return 'NS_making' if made[0] else 'NS_down'
    if any(c == dict(level=2, strain='S', declarer='E', doubled=1) for c in contracts):
        assert not made[0]
        return 'EW_2SX_available'
    if not made[0]:
        return 'EW_other_down'
    games = [c['level'] >= {'N': 3, 'S': 4, 'H': 4, 'D': 5, 'C': 5}[c['strain']]
             for c in contracts]
    assert len(set(games)) == 1, 'Ambiguous game/partscore classification'
    return 'EW_making_game' if games[0] else 'EW_making_partscore'


def csv_write(path, rows):
    rows = list(rows)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path, nargs='?',
                        default=Path(__file__).resolve().parent / 'run_v5_10000')
    args = parser.parse_args()
    run = args.run_dir
    out = run / 'contract_analysis'
    out.mkdir(exist_ok=True)
    rows = [json.loads(s) for s in (run / 'results.jsonl').read_text().splitlines()]
    dd = {r['number']: r for r in map(json.loads, (run / 'dds.jsonl').read_text().splitlines())}
    base = json.loads((run / 'summary.json').read_text())
    n = len(rows)
    assert n == 10000 and sum(r['delta_imp'] for r in rows) == 4889
    groups, exact, merged = defaultdict(list), defaultdict(list), defaultdict(list)
    unique_labels = Counter()
    transitions, par_scores, tricks = defaultdict(list), defaultdict(list), defaultdict(list)
    board_rows = []
    for r in rows:
        assert r['pbn'] == dd[r['number']]['pbn']
        assert r['pbn'].split()[2] == '3.9754.AKT8.A764'
        assert r['delta_ns'] == r['double_par_score_ns'] - r['pass_score_ns']
        cat = component(r, dd[r['number']]['dd_table_CDHSN_NESW'])
        groups[cat].append(r)
        labels = set(label(c) for c in r['optimal_contracts'])
        precise = set(label(c, True) for c in r['optimal_contracts'])
        if len(labels) == 1:
            unique_labels.update(labels)
        for key in labels:
            merged[key].append(r)
        for key in precise:
            exact[key].append(r)
        transitions[(r['pass_score_ns'], r['double_par_score_ns'])].append(r)
        par_scores[r['double_par_score_ns']].append(r)
        tricks[r['east_2S_tricks']].append(r)
        board_rows.append(dict(number=r['number'], category=cat,
                               east_2S_tricks=r['east_2S_tricks'],
                               pass_score_ns=r['pass_score_ns'],
                               double_par_score_ns=r['double_par_score_ns'],
                               delta_ns=r['delta_ns'], delta_imp=r['delta_imp'],
                               bam_points=r['bam_points'],
                               optimal_contract_count=len(precise),
                               optimal_label_count=len(labels),
                               merged_optimal_contracts='; '.join(sorted(labels)),
                               exact_optimal_contracts='; '.join(sorted(precise)),
                               pbn=r['pbn'], handviewer_url=r['handviewer_url']))

    presence = []
    for name, members in sorted(merged.items(), key=lambda x: (-len(x[1]), x[0])):
        presence.append(dict(contract=name, **stats(members, n),
                             unique_label_boards=unique_labels[name],
                             forced_selection_lower_bound=unique_labels[name] / n,
                             possible_selection_upper_bound=len(members) / n))
    precise = [dict(contract=k, **stats(v, n))
               for k, v in sorted(exact.items(), key=lambda x: (-len(x[1]), x[0]))]
    order = ['NS_down', 'NS_making', 'EW_2SX_available', 'EW_making_partscore',
             'EW_making_game', 'EW_other_down', 'mixed_NS_making_or_EW_down']
    components = [dict(category=k, **stats(groups[k], n)) for k in order]
    for table in (components,):
        assert sum(x['n'] for x in table) == n
        assert sum(x['sum_imp'] for x in table) == 4889
    impfreq = Counter(r['delta_imp'] for r in rows)
    imp_table = [dict(imp_diff=i, n=impfreq[i], frequency=impfreq[i] / n,
                      sum_imp=i * impfreq[i], contribution_to_overall_mean=i * impfreq[i] / n)
                 for i in range(min(impfreq), max(impfreq) + 1)]
    score_table = [dict(par_score_ns=k, **stats(v, n)) for k, v in sorted(par_scores.items())]
    trick_table = [dict(east_2S_tricks=k, **stats(v, n)) for k, v in sorted(tricks.items())]
    transition_table = [dict(pass_score_ns=k[0], double_par_score_ns=k[1], **stats(v, n))
                        for k, v in sorted(transitions.items(), key=lambda x: (-len(x[1]), x[0]))]
    bands = [dict(band=k, **stats([r for r in rows if p(r['delta_imp'])], n)) for k, p in [
        ('loss_8_plus', lambda i: i <= -8), ('loss_1_to_7', lambda i: -7 <= i <= -1),
        ('zero', lambda i: i == 0), ('gain_1_to_7', lambda i: 1 <= i <= 7),
        ('gain_8_plus', lambda i: i >= 8)]]
    assert sum(x['n'] for x in bands) == n
    assert sum(x['sum_imp'] for x in imp_table) == sum(x['sum_imp'] for x in bands) == 4889
    assert {str(x['imp_diff']): x['n'] for x in imp_table if x['n']} == base['imp_distribution']
    assert {str(x['par_score_ns']): x['n'] for x in score_table} == base['double_par_score_distribution']
    overview = dict(**stats(rows, n), mean_imp_bootstrap_95=base['mean_imp_bootstrap_95'],
                    bam_bootstrap_95=base['bam_mean_points_bootstrap_95'],
                    mean_pass_score_ns=base['mean_pass_score'],
                    mean_double_par_score_ns=base['mean_double_par_score'],
                    mean_raw_delta=base['mean_raw_delta'],
                    imp_positive=sum(r['delta_imp'] > 0 for r in rows),
                    imp_zero=impfreq[0], imp_negative=sum(r['delta_imp'] < 0 for r in rows),
                    raw_win_but_zero_imp=sum(r['delta_ns'] > 0 and r['delta_imp'] == 0 for r in rows),
                    gross_positive_imp=sum(max(0, r['delta_imp']) for r in rows),
                    gross_negative_imp=sum(min(0, r['delta_imp']) for r in rows),
                    multiple_exact_contracts=sum(r['optimal_contract_count'] > 1 for r in board_rows),
                    multiple_merged_labels=sum(r['optimal_label_count'] > 1 for r in board_rows),
                    total_merged_label_presence=sum(x['n'] for x in presence))
    report = dict(dataset=str(run.resolve()), fixed_south='S:3 H:9754 D:AKT8 C:A764',
                  vulnerability='NS nonvulnerable; EW vulnerable',
                  auction='N:P E:1S S:X W:P N:1NT E:2H S:P W:2S N:P E:P S:?',
                  definitions={
                      'outcome': 'Saved exact history-constrained perfect-information continuation Par after South X, West next; all players unrestricted.',
                      'baseline': 'East 2S undoubled, double-dummy tricks.',
                      'delta': 'Double-Par NS score minus Pass NS score; convert each deal to IMP, then average.',
                      'presence': 'Each deal counts once per side/level/strain/double label. Optimal labels overlap. No behavioral selection probabilities are assumed.',
                      'bounds': 'Lower/upper bounds apply only to selecting one of the stored cooptimal labels, not to actual human play.',
                      'components': 'Mutually exclusive exhaustive categories using all cooptimal contracts and saved DD trick counts.',
                      'BAM': 'Raw score win=1, tie=0.5, loss=0. This is a head-to-head comparison, not an actual field MP percentage.',
                      'uncertainty': 'Intervals cover Monte Carlo sampling uncertainty conditional on filters and the Par model, not model error.',
                  }, overview=overview, contract_presence=presence,
                  components=components, imp_frequency=imp_table, imp_bands=bands,
                  par_score_frequency=score_table, baseline_2S_tricks=trick_table,
                  score_transitions=transition_table,
                  source_sha256={name: hashlib.sha256((run / name).read_bytes()).hexdigest()
                                 for name in ['results.jsonl', 'dds.jsonl', 'deals.json', 'summary.json']},
                  no_dds_or_par_recomputed=True)
    (out / 'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for name, data in [('contract_presence', presence), ('exact_contract_presence', precise),
                       ('components', components), ('imp_frequency', imp_table), ('imp_bands', bands),
                       ('par_score_frequency', score_table), ('baseline_2S_tricks', trick_table),
                       ('score_transitions', transition_table), ('board_diagnostics', board_rows)]:
        csv_write(out / f'{name}.csv', data)
    (out / 'README.txt').write_text('''最新版 DK 一萬副：保存樣本的事後分析
固定南家：S3 H9754 DAKT8 CA764；我方無身價、敵方有身價。
來源：run_v5_10000，平均賭倍優勢 +0.4889 IMP。沒有重抽樣或重算 DDS/Par。

report.pdf：繁中完整報告，適合手機閱覽。
overview.png：摘要圖。
analysis.json：核心統計、定義與來源 SHA256。
contract_presence.csv：合併同方宣告人的合約出現率，互相重疊，不能加總。
exact_contract_presence.csv：保留宣告人的合約出現率。
components.csv：互斥七類及對全體平均 IMP 的貢獻，可相加。
imp_frequency.csv / imp_bands.csv：IMP diff 分布。
par_score_frequency.csv：每副唯一的 Par 分數分布，可相加。
baseline_2S_tricks.csv：按原合約東家2S的雙明手墩數分組。
score_transitions.csv：Pass 分數到賭倍 Par 分數的轉移。
board_diagnostics.csv：逐副分類、所有最優終約與 Handviewer URL。
factors.json / factors.csv：13種隱藏手牌因素分組及調整後相關性。
heart_component_cross.json / CSV：同伴紅心與受罰、敵方成局的交叉分析。

Par 保留完整既有叫序，南家賭倍後由西家開始，四家可自由競叫。
多個最優終約分數完全相同；沒有為各終約設定人類選擇機率。
BAM=(原始分贏副數+0.5*平副數)/10000，不是實際賽場MP百分比。
IMP diff 每副先換算才平均，正值有利賭倍。
所有信賴區間僅反映指定篩牌及Par模型下的抽樣誤差。
手牌因素是事後關聯，不能當作南家當場已知資訊或因果關係。

壓縮檔解開後，在其根目錄依序執行：
python scripts/analyze_dk_contracts.py source_run
python scripts/analyze_dk_factors.py source_run
python scripts/analyze_dk_heart_components.py source_run
python scripts/render_dk_analysis.py source_run
需要 Python 3、numpy、scipy、matplotlib；報表需要 Noto Sans CJK 字型。
scripts/heart_strength_analysis.py 僅供匯入固定效果估計函式，毋須直接執行。
''', encoding='utf-8')
    print(json.dumps(overview, indent=2))


if __name__ == '__main__':
    main()
