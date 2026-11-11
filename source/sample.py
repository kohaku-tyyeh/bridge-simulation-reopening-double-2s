#!/usr/bin/env python3
"""發牌：固定南家，其餘 39 張以 random.Random(seed) 原地洗牌，
N=deck[0:13], E=deck[13:26], W=deck[26:39]，用 filters/filter_deals.py 的規則拒絕。
按產生順序取前 N 副；定期 checkpoint（亂數狀態、牌堆、計數、輸出游標）。"""
import argparse, json, os, random, sys, time
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).with_name('filters')))
import filter_deals as F  # 只用 Hand、east/north/west_failures、deal_failures；不用它的 main()

SUITS = "SHDC"
def hand_str(h):  # PBN 順序 S.H.D.C
    return ".".join(h.suits)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--count', type=int, default=10000)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--ckpt-every', type=int, default=250)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rules = json.loads((Path(__file__).with_name('filters') / 'rules.json').read_text())
    south = F.Hand(F.FIXED_SOUTH)
    deals_path = a.out / 'deals.jsonl'
    ck_path = a.out / 'checkpoint.json'
    if ck_path.exists():
        ck = json.loads(ck_path.read_text())
        assert ck['seed'] == a.seed
        rng = random.Random(); st = ck['rng_state']
        rng.setstate((st[0], tuple(st[1]), st[2]))
        deck = ck['deck']; attempts = ck['attempts']; accepted = ck['accepted']
        rej = Counter(ck['rejections']); seen = set(ck['seen'])
        # 截掉 checkpoint 之後的輸出，避免重複
        lines = deals_path.read_text().splitlines()[:accepted]
        deals_path.write_text(''.join(l + '\n' for l in lines))
    else:
        rng = random.Random(a.seed)
        deck = [c for c in range(52) if c not in set(south.cards)]
        attempts = accepted = 0; rej = Counter(); seen = set()
        deals_path.write_text('')
    assert len(deck) == 39 and not set(deck) & set(south.cards)
    fout = deals_path.open('a')
    t0 = time.monotonic()
    def checkpoint():
        fout.flush(); os.fsync(fout.fileno())
        st = rng.getstate()
        tmp = ck_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(seed=a.seed, rng_state=[st[0], list(st[1]), st[2]],
            deck=deck, attempts=attempts, accepted=accepted, rejections=rej,
            seen=sorted(seen), saved=time.strftime('%Y-%m-%d %H:%M:%S'))))
        os.replace(tmp, ck_path)
    while accepted < a.count:
        rng.shuffle(deck); attempts += 1
        e = deck[13:26]
        # 快速必要條件（east_failures 隱含）：東家 ♠>=5、♥>=4；不合者記 prefilter
        ns = sum(1 for c in e if c < 13); nh = sum(1 for c in e if 13 <= c < 26)
        if ns < 5 or nh < 4:
            rej['prefilter_E_majors'] += 1; continue
        E = F.Hand.from_cards(e); f = F.east_failures(E, rules)
        if f: rej[f[0]] += 1; continue
        N = F.Hand.from_cards(deck[0:13]); f = F.north_failures(N, rules)
        if f: rej[f[0]] += 1; continue
        W = F.Hand.from_cards(deck[26:39]); f = F.west_failures(W, rules)
        if f: rej[f[0]] += 1; continue
        deal = dict(N=N, E=E, S=south, W=W)
        assert not F.deal_failures(deal, rules)
        ident = " ".join(hand_str(deal[s]) for s in "NESW")
        if ident in seen: rej['duplicate'] += 1; continue
        seen.add(ident); accepted += 1
        fout.write(json.dumps(dict(board=accepted, attempt=attempts,
            pbn="N:" + ident)) + '\n')
        if accepted % a.ckpt_every == 0:
            checkpoint()
            print(f'{time.strftime("%H:%M:%S")} accepted {accepted} attempts {attempts:,} '
                  f'{time.monotonic()-t0:.0f}s', flush=True)
    checkpoint(); fout.close()
    (a.out / 'sampling_summary.json').write_text(json.dumps(dict(seed=a.seed,
        count=a.count, attempts=attempts, acceptance=accepted/attempts,
        rejection_first_reason=dict(rej.most_common())), indent=1))
    print('done', accepted, attempts)

if __name__ == '__main__':
    main()
