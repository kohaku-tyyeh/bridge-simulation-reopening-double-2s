"""Targeted regression checks for the isolated NS three-level no-double policy.

Run: python3 test_continuation_par_policy.py [--output report.json]
Uses original solver only for mask-zero regression; native policy legality,
hand-calculated controlled outcomes, and independent PV replay cover changes.
"""

import argparse
from dataclasses import replace
import itertools
import json
from pathlib import Path

import continuation_par as original
import continuation_par_policy as policy
from test_continuation_par import (
    AuctionState as OracleState, INITIAL, actions, advance, terminal_score,
)


def state_at(level, strain, declarer=0, doubled=0, next_player=1, passes=2):
    first = [[0] * 5 for _ in range(2)]
    first[declarer % 2][strain] = declarer // 2 + 1
    return policy.AuctionState(
        bid=(level - 1) * 5 + strain, declarer=declarer,
        doubled=doubled, passes=passes, next_player=next_player,
        first_decl=tuple(map(tuple, first)),
    )


def forbidden(state, raw_action, mask):
    """Independent condition expressed in contract/seat terminology."""
    if raw_action != -2:
        return False
    return (
        state.bid in (10, 11, 12, 13)
        and state.declarer in (0, 2)
        and state.next_player in (1, 3)
        and state.doubled == 0
        and bool(mask & (1 << (state.bid - 10)))
    )


def verify_policy_pv(table, result, mask, initial=INITIAL):
    state = initial
    for i, raw in enumerate(result['actions']):
        assert not forbidden(state, raw, mask), (state, raw, mask)
        action = {-1: 'P', -2: 'X', -3: 'XX'}.get(raw, raw)
        assert action in set(actions(state)), (state, action)
        nxt = advance(state, action)
        if nxt is None:
            assert i + 1 == len(result['actions'])
            assert terminal_score(state, table) == result['score_ns']
            assert result['contract'] == {
                'level': state.bid // 5 + 1, 'strain': 'CDHSN'[state.bid % 5],
                'declarer': 'NESW'[state.declarer], 'doubled': state.doubled,
            }
        else:
            assert i + 1 < len(result['actions'])
            state = nxt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    counters = {}

    # All four suits, either NS declarer, either EW doubler, and each pass count.
    count = 0
    for strain, declarer, next_player, passes in itertools.product(
            range(4), (0, 2), (1, 3), range(3)):
        state = state_at(3, strain, declarer=declarer,
                         next_player=next_player, passes=passes)
        assert policy.is_legal_action(state, -2, 0)
        assert not policy.is_legal_action(state, -2, 1 << strain)
        assert policy.is_legal_action(state, -2, 16)
        assert policy.is_legal_action(state, -1, 31)
        assert policy.is_legal_action(state, state.bid + 1, 31)
        count += 1
    counters['targeted_legality_states'] = count

    for level in (1, 2, 4, 5, 6, 7):
        for strain in range(5):
            assert policy.is_legal_action(state_at(level, strain), -2, 31)
    assert policy.is_legal_action(state_at(3, 4), -2, 31)  # 3NT unchanged.
    for strain in range(4):
        assert policy.is_legal_action(
            state_at(3, strain, declarer=1, next_player=0), -2, 31)
        assert policy.is_legal_action(
            state_at(3, strain, doubled=1, next_player=0), -3, 31)
    # Starting 2S by East remains doubled; West can still redouble.
    assert policy.AuctionState().doubled == 1
    assert policy.is_legal_action(policy.AuctionState(), -3, 31)
    counters['boundary_conditions'] = 40

    # Controlled full-search outcomes: each NS three-level suit is down one.
    # All alternative strains are disastrous, so forbidding X changes -100 to -50.
    fixtures = []
    for strain in range(4):
        table = [[0] * 4 for _ in range(5)]
        table[strain][0] = table[strain][2] = 8
        initial = state_at(3, strain)
        baseline = policy.solve(table, state=initial, blocked_ns_level3_strains=0)
        restricted = policy.solve(table, state=initial,
                                  blocked_ns_level3_strains=1 << strain)
        assert baseline['score_ns'] == -100, (strain, baseline)
        assert restricted['score_ns'] == -50, (strain, restricted)
        assert restricted['optimal_contracts'] == [{
            'level': 3, 'strain': 'CDHS'[strain], 'declarer': 'N', 'doubled': 0,
        }]
        # A double already present in the initial state must not be undone.
        doubled = policy.solve(table, state=replace(initial, doubled=1),
                               blocked_ns_level3_strains=1 << strain)
        assert doubled['score_ns'] == -100
        assert doubled['contract']['doubled'] == 1
        # At level four, the same ban has no effect: down two doubled = -300.
        level_four = policy.solve(table, state=state_at(4, strain),
                                  blocked_ns_level3_strains=1 << strain)
        assert level_four['score_ns'] == -300
        fixtures.append({'strain': 'CDHS'[strain], 'unrestricted': -100,
                         'restricted': -50, 'preexisting_double': -100,
                         'level_four_unaffected': -300})
    counters['controlled_search_fixtures'] = fixtures

    root = Path(__file__).parent
    source = root / 'run_v5_10000' / 'dds.jsonl'
    records = list(itertools.islice((json.loads(s) for s in source.open()), 100))
    assert len(records) == 100
    for record in records:
        table = record['dd_table_CDHSN_NESW']
        baseline = original.solve(table)
        mask_zero = policy.solve(table, blocked_ns_level3_strains=0)
        for key in ('score_ns', 'optimal_contracts', 'contract', 'actions'):
            assert baseline[key] == mask_zero[key], (record['number'], key)
        all_suits = policy.solve(table, blocked_ns_level3_strains=15)
        assert all_suits['score_ns'] >= baseline['score_ns']
        for contract in all_suits['optimal_contracts']:
            assert not (contract['declarer'] in 'NS' and contract['level'] == 3
                        and contract['strain'] in 'CDHS' and contract['doubled'])
        verify_policy_pv(table, mask_zero, 0)
        verify_policy_pv(table, all_suits, 15)
        nt_bit = policy.solve(table, blocked_ns_level3_strains=16)
        assert nt_bit['score_ns'] == baseline['score_ns']
        assert nt_bit['optimal_contracts'] == baseline['optimal_contracts']
    counters['real_deal_mask0_score_set_and_pv_matches'] = 100
    counters['real_deal_all_suit_mask_monotonicity_and_pv_checks'] = 100
    counters['real_deal_nt_bit_ignored_checks'] = 100
    counters['status'] = 'PASS'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(counters, indent=2) + '\n')
    print(json.dumps(counters, indent=2))


if __name__ == '__main__':
    main()
