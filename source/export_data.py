#!/usr/bin/env python3
"""由執行輸出（deals.jsonl、results.jsonl）產生 data/ 下的整理檔：
deals.pbn、results.jsonl、results.csv、schema.json。"""
import csv, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).with_name('filters')))
import common as C
import filter_deals as F

SCEN = {'a': 'original', 'b': 'protect_32', 'c': 'protect_32_41'}
PREFIX = ['P', '1S', 'X', 'P', '1NT', '2H', 'P', '2S', 'P', 'P']
SEATS = 'NESW'

def tok(c):  # 內部叫品 -> 顯示
    return c[0] + 'NT' if len(c) == 2 and c[1] == 'N' else c

def hv_call(c):
    return {'P': 'p', 'X': 'd', 'XX': 'r'}.get(c, c.lower().replace('nt', 'n'))

def handviewer(board, pbn, auction):
    h = C.parse_pbn(pbn)
    hands = '&'.join(f"{s.lower()}=" + ''.join(x + r.lower() for x, r in zip('shdc', h[s])) for s in SEATS)
    return (f"https://www.bridgebase.com/tools/handviewer.html?b={board}&d=n&v=e&{hands}"
            f"&a={''.join(hv_call(c) for c in auction)}")

def contract_obj(o, dd):
    con, decl = o.split('-')
    lv, st, dbl = int(con[0]), con[1], con[2:].count('X')
    t = dd[(st, decl)]
    return dict(level=lv, strain=st, declarer=decl, doubled=dbl,
                label=f"{lv}{'NT' if st == 'N' else st}{'X' * dbl} {decl}", dd_tricks=t,
                result_tricks=t - (lv + 6), score_ns=C.score_ns(con, decl, dd))

def with_seats(auction):
    return [dict(seat=SEATS[i % 4], call=c) for i, c in enumerate(auction)]

def main(run_dir, data_dir):
    run_dir, data_dir = Path(run_dir), Path(data_dir); data_dir.mkdir(parents=True, exist_ok=True)
    rules = json.loads((Path(__file__).with_name('filters') / 'rules.json').read_text())
    deals = {d['board']: d for d in map(json.loads, (run_dir / 'deals.jsonl').read_text().splitlines())}
    rows = [json.loads(l) for l in (run_dir / 'results.jsonl').read_text().splitlines()]
    out, flat, pbn_txt = [], [], []
    for r in rows:
        b, pbn = r['board'], r['pbn']
        assert deals[b]['pbn'] == pbn
        h = C.parse_pbn(pbn); C.check_deal(h)
        H = {s: F.Hand(tuple(h[s])) for s in SEATS}
        filt = dict(E=F.east_failures(H['E'], rules), N=F.north_failures(H['N'], rules),
                    W=F.west_failures(H['W'], rules), deal=F.deal_failures(H, rules))
        assert not any(filt.values())
        dd = {(k[0], k[1]): v for k, v in r['dd'].items()}
        pass_auction = PREFIX + ['P']
        rec = dict(board=b, dealer='N', vulnerability='EW', pbn=pbn,
                   hands={s: dict(zip('SHDC', h[s])) for s in SEATS},
                   hand_metrics={s: dict(hcp=H[s].hcp, shape_SHDC=list(H[s].shape), basic_ltc=H[s].losing_tricks)
                                 for s in SEATS},
                   sampling=dict(shuffle_index=deals[b]['attempt']),
                   filters=dict(passed=True, failures=filt),
                   dd_table=dict(strains=list('CDHSN'), seats=list(SEATS),
                                 tricks=[[dd[(s, x)] for x in SEATS] for s in 'CDHSN']),
                   pass_branch=dict(full_auction=pass_auction, 
                                    contract=contract_obj('2S-E', dd), score_ns=r['pass_score'],
                                    handviewer_url=handviewer(b, pbn, pass_auction)))
        assert rec['pass_branch']['contract']['score_ns'] == r['pass_score']
        rec['double_branches'] = {}
        f = dict(board=b, pbn=pbn, N_hcp=H['N'].hcp, E_hcp=H['E'].hcp, W_hcp=H['W'].hcp,
                 **{f'dd_{s}_{x}': dd[(s, x)] for s in 'CDHSN' for x in SEATS},
                 pass_score=r['pass_score'])
        for k, name in SCEN.items():
            x = r[k]
            auc = PREFIX + ['X'] + [tok(c) for c in x['continuation']]
            assert auc[-3:] == ['P', 'P', 'P']
            rep = contract_obj(x['rep'], dd); assert rep['score_ns'] == x['score']
            opts = [contract_obj(o, dd) for o in x['outcomes']]
            assert all(o['score_ns'] == x['score'] for o in opts)
            rec['double_branches'][name] = dict(
                full_auction=auc, contract=rep,
                score_ns=x['score'], delta_score_ns=x['diff'], imp=x['imp'], bam=x['bam'],
                optimal_contracts=opts, optimal_contract_count=len(opts),
                best_contract_unique=len(opts) == 1, handviewer_url=handviewer(b, pbn, auc))
            f.update({f'{name}_contract': rep['label'], f'{name}_dd_tricks': rep['dd_tricks'],
                      f'{name}_score': x['score'], f'{name}_delta': x['diff'], f'{name}_imp': x['imp'],
                      f'{name}_bam': x['bam'], f'{name}_optimal': ';'.join(o['label'] for o in opts),
                      f'{name}_unique': int(len(opts) == 1), f'{name}_auction': ' '.join(auc)})
        out.append(rec); flat.append(f)
        pbn_txt.append('\n'.join([f'[Event "Reopening double over 2S"]', '[Site "Simulation"]', f'[Board "{b}"]',
                                  '[Dealer "N"]', '[Vulnerable "EW"]', f'[Deal "{pbn}"]']) + '\n')
    (data_dir / 'results.jsonl').write_text(''.join(json.dumps(o, ensure_ascii=False, separators=(',', ':')) + '\n' for o in out))
    with open(data_dir / 'results.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(flat[0])); w.writeheader(); w.writerows(flat)
    (data_dir / 'deals.pbn').write_text('\n'.join(pbn_txt))
    schema = {
        'format': 'JSON Lines，每副一筆；results.csv 為同內容的扁平表。主鍵 board（按產生順序的牌號）。',
        'pbn': 'PBN Deal 標籤格式，從北家起依 N E S W，花色順序 S H D C。',
        'vulnerability': 'EW：東西有身價，南北無身價。北家發牌。',
        'hand_metrics': '各家 HCP、牌型（S H D C 張數）、基本失墩數（不調整）。',
        'sampling.shuffle_index': '這副牌在洗牌序列中的序號（第幾次洗牌）。',
        'filters': '各家篩牌條件的失敗原因清單（全部為空才入樣）；只用牌張與叫牌，不用雙夢家或續叫結果。',
        'dd_table': 'tricks[王牌][座位]：該座位作莊、該王牌的雙夢家墩數；王牌順序 C D H S N（N=無王），座位 N E S W。',
        'pass_branch': '南家 Pass，叫牌結束，東家打未賭倍的 2♠。',
        'double_branches': {
            'original': '南家重開賭倍後由西家續叫，四家全資訊、保留叫序的續叫 Par（所有合法叫品）。',
            'protect_32': '同上，但南北在三線打有王合約、南北合計恰好八張王牌、東西王牌 3–2 時，東西不得賭倍。',
            'protect_32_41': '同上，保護範圍加上東西王牌 4–1；5–0、3NT、其他線位不保護。'},
        'full_auction': '從北家起的完整叫序，結尾為三個 P。X=賭倍，XX=再賭倍，NT=無王。',
        'contract': '代表終局：level、strain（N=無王）、declarer、doubled（0/1/2）、dd_tricks、result_tricks（相對合約的超墩或宕墩）、score_ns（南北分數）。',
        'delta_score_ns': '重開賭倍分數減 Pass 分數（南北立場）。',
        'imp': '逐副分差換算的 IMP。', 'bam': 'BAM：勝 1、和 0.5、負 0。',
        'optimal_contracts': '所有最佳終局（雙方每步任選一個最佳叫品可走到的終局，含莊家與加倍），分數全相同。',
        'best_contract_unique': '最佳終局是否唯一；最佳叫牌路徑是否唯一未記錄。',
        'full_auction 的續叫部分': '搜尋找到的一條最佳路徑（每步取第一個最佳叫品：Pass、X、XX、低叫品優先）；中間叫品沒有約定意義。',
        'handviewer_url': 'BBO Handviewer 連結，b=牌號，a=打到最後一個 Pass。'}
    (data_dir / 'schema.json').write_text(json.dumps(schema, ensure_ascii=False, indent=1) + '\n')
    print('exported', len(out))

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
