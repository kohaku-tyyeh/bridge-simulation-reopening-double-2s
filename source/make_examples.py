#!/usr/bin/env python3
"""文章牌例：從 data/results.jsonl 取出指定牌號，寫 data/examples.json（URL 由資料生成）。"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = [
    (460, '同伴罰放：2♠X 宕二', 'original'),
    (367, '轉打我方部分合約：梅花 4–4 配合', 'original'),
    (657, '沒有配合：2NTX 宕三', 'original'),
    (82, '東家額外牌力：叫到 4♠', 'original'),
    (5980, '保護 3–2 改變結果：IMP 與 BAM 的差別', 'protect_32'),
    (1916, '只有保護 4–1 才改變結果', 'protect_32_41'),
]
rows = {json.loads(l)['board']: json.loads(l) for l in (ROOT / 'data/results.jsonl').read_text().splitlines()}
out = []
for b, mech, focus in EXAMPLES:
    r = rows[b]
    out.append(dict(board=b, mechanism=mech, focus_scenario=focus, pbn=r['pbn'],
                    pass_branch=dict(contract=r['pass_branch']['contract']['label'], score_ns=r['pass_branch']['score_ns'],
                                     handviewer_url=r['pass_branch']['handviewer_url']),
                    double_branches={k: dict(contract=d['contract']['label'], dd_tricks=d['contract']['dd_tricks'],
                                             score_ns=d['score_ns'], imp=d['imp'], bam=d['bam'],
                                             best_contract_unique=d['best_contract_unique'],
                                             full_auction=' '.join(d['full_auction']), handviewer_url=d['handviewer_url'])
                                     for k, d in r['double_branches'].items()}))
(ROOT / 'data/examples.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
print('examples', [e['board'] for e in out])
