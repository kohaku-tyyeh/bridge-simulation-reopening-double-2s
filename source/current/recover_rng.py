"""Restore the exact v6 shuffle stream without filtering or solving old deals."""
import json
from pathlib import Path
import random
import time

from filter_deals import Hand, FIXED_SOUTH, SUITS

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / 'run_v6_10000'


def main():
    source = json.loads((OLD / 'deals.json').read_text())
    fixed = set(Hand(FIXED_SOUTH).cards)
    unknown = [c for c in range(52) if c not in fixed]
    rng = random.Random(source['seed'])
    start = time.monotonic()
    for i in range(1, source['attempts'] + 1):
        rng.shuffle(unknown)
        if i % 2_000_000 == 0:
            print(f'Replay {i:,}/{source["attempts"]:,}; {time.monotonic()-start:.1f}s', flush=True)
    last = source['deals'][-1]
    for seat, cards in [('E', unknown[:13]), ('N', unknown[13:26]), ('W', unknown[26:])]:
        assert dict(zip(SUITS, Hand.from_cards(cards).suits)) == last['hands'][seat]['suits']
    checkpoint = dict(seed=source['seed'], attempts=source['attempts'],
                      random_state=rng.getstate(), unknown_deck=unknown,
                      last_v6_deal_verified=True, seconds=time.monotonic()-start)
    (ROOT / 'rng_after_v6.json').write_text(json.dumps(checkpoint) + '\n')
    print(f'Exact v6 endpoint restored and verified; {checkpoint["seconds"]:.1f}s', flush=True)


if __name__ == '__main__':
    main()
