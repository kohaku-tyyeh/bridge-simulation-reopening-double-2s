"""Keep approved v6 deals and continue its exact shuffle stream to 10,000."""
from collections import Counter
import copy
import csv
import hashlib
import json
from pathlib import Path
import random
import time

import filter_deals as f
from dds_backend import pbn
from nt_choice import classify

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / 'run_v6_10000'
SUPP = ROOT / 'supplement'


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def record(deal, number, attempt, source_number):
    north = deal['N']
    return dict(number=number,
                hands={s: dict(suits=dict(zip(f.SUITS, deal[s].suits)),
                               hcp=deal[s].hcp, shape_SHDC=list(deal[s].shape),
                               balanced=deal[s].balanced, basic_ltc=deal[s].losing_tricks)
                       for s in 'NESW'},
                north_penalty_check=dict(
                    spade_promotion_floor=f.trump_promotion_floor(north.suits[0]),
                    spade_knr_points=f.knr_suit_points(north.suits[0]) if len(north.suits[0]) in (4, 5) else None,
                    best_four_spade_knr_points=max(f.knr_suit_points(north.suits[0][:i]+north.suits[0][i+1:])
                        for i in range(5)) if len(north.suits[0]) == 5 else None,
                    penalty_reason=f.penalty_reason(north, RULES)),
                handviewer_url=f.viewer_link(deal), source_run='v7_supplement',
                source_number=source_number, source_shuffle_index=attempt)


RULES = json.loads(Path(__file__).with_name('rules.json').read_text())


def main():
    assert not (ROOT / 'deals.json').exists(), 'Do not overwrite completed sampling'
    old = json.loads((OLD / 'deals.json').read_text())
    checkpoint = json.loads((ROOT / 'rng_after_v6.json').read_text())
    assert checkpoint['attempts'] == old['attempts'] and checkpoint['seed'] == old['seed']
    assert checkpoint['last_v6_deal_verified']
    preview = json.loads((ROOT.parent / 'preview_v6_nt_choice/analysis.json').read_text())
    retained = [copy.deepcopy(d) for d in old['deals'] if not classify(d['hands']['N']['suits'])['reject']]
    assert [d['number'] for d in retained] == preview['retained_ids']
    assert len(retained) == 9128
    for i, d in enumerate(retained, 1):
        d['source_run'], d['source_number'], d['number'] = 'run_v6_10000', d['number'], i
        hands = {s: f.Hand(tuple(d['hands'][s]['suits'][x] for x in f.SUITS)) for s in 'NESW'}
        assert not f.deal_failures(hands, RULES)
    rng = random.Random()
    state = checkpoint['random_state']
    rng.setstate((state[0], tuple(state[1]), state[2]))
    unknown = checkpoint['unknown_deck']
    seen = {pbn(d) for d in old['deals']}
    south = f.Hand(f.FIXED_SOUTH)
    accepted, reasons = [], Counter()
    start = time.monotonic()
    for step in range(1, 20_000_001):
        rng.shuffle(unknown)
        if step % 250_000 == 0:
            print(f'Additional shuffles {step:,}; accepted {len(accepted)}/872; {time.monotonic()-start:.1f}s', flush=True)
        east = f.Hand.from_cards(unknown[:13])
        failures = f.east_failures(east, RULES)
        if failures:
            reasons[failures[0]] += 1
            continue
        north = f.Hand.from_cards(unknown[13:26])
        failures = f.north_failures(north, RULES)
        if failures:
            reasons[failures[0]] += 1
            continue
        west = f.Hand.from_cards(unknown[26:])
        failures = f.west_failures(west, RULES)
        if failures:
            reasons[failures[0]] += 1
            continue
        deal = dict(N=north, E=east, S=south, W=west)
        assert not f.deal_failures(deal, RULES)
        d = record(deal, len(retained) + len(accepted) + 1,
                   old['attempts'] + step, len(accepted) + 1)
        key = pbn(d)
        if key in seen:
            reasons['duplicate'] += 1
            continue
        seen.add(key)
        accepted.append(d)
        if len(accepted) == 872:
            break
    assert len(accepted) == 872
    assert sum(reasons.values()) + len(accepted) == step
    sampling = dict(method='Exact continuation of random.Random(seed) in-place uniform shuffle of 39 unknown cards',
                    seed=old['seed'], source_attempts=old['attempts'], additional_attempts=step,
                    total_stream_attempts=old['attempts'] + step,
                    source_accepted=10000, source_retained=9128, source_rejected_by_new_rule=872,
                    additional_accepted=872, replayed_shuffles_are_not_new_attempts=True,
                    additional_rejection_first_reason_counts=dict(reasons),
                    additional_generation_seconds=time.monotonic()-start,
                    source_rejection_counts_not_reclassified=True,
                    stopping_rule='Stop at 10,000 qualifying deals, independent of outcomes')
    payload = dict(seed=old['seed'], attempts=old['attempts'] + step, rules=RULES,
                   generation_seconds=sampling['additional_generation_seconds'],
                   dealer='N', vulnerability='EW', next_to_act='S', auction=f.AUCTION,
                   sampling=sampling, deals=retained + accepted)
    write_json(ROOT / 'deals.json', payload)
    supplement = dict(payload, attempts=step, deals=accepted)
    write_json(SUPP / 'deals.json', supplement)
    for directory, records in [(ROOT, payload['deals']), (SUPP, accepted)]:
        (directory / 'handviewer_links.txt').write_text(''.join(f'{d["number"]}. {d["handviewer_url"]}\n' for d in records))
    write_json(ROOT / 'rng_checkpoint.json', dict(seed=old['seed'], attempts=payload['attempts'],
               random_state=rng.getstate(), unknown_deck=unknown,
               accepted_final_count=10000, last_pbn=pbn(accepted[-1])))
    with (ROOT / 'provenance.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['number', 'source_run', 'source_number', 'source_shuffle_index'])
        writer.writeheader()
        writer.writerows({key: d.get(key, '') for key in writer.fieldnames} for d in payload['deals'])
    write_json(ROOT / 'sampling_manifest.json', sampling)
    print(json.dumps(sampling, indent=2), flush=True)


if __name__ == '__main__':
    main()
