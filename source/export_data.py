#!/usr/bin/env python3
"""Export saved bridge outcomes, including only actually recorded search auctions.

Usage: python source/export_data.py RUN_DIR OUTPUT_DATA_DIR
No deal generation, DDS call or Par search is performed by this exporter.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

SEATS = 'NESW'
SUITS = 'SHDC'
DD_STRAINS = 'CDHSN'
MODELS = {
    'original': 'results.jsonl',
    'protect_32': 'no_double_policy/protect_32.jsonl',
    'protect_32_41': 'no_double_policy/protect_32_41.jsonl',
}


def read_rows(path):
    rows = [json.loads(s) for s in path.read_text().splitlines() if s.strip()]
    indexed = {r['number']: r for r in rows}
    assert len(rows) == len(indexed), f'Duplicate board IDs: {path}'
    return indexed


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(call):
    if call == 'D':
        return 'X'
    if call.endswith('N') and call[0] in '1234567':
        return call + 'T'
    return call


def contract_key(c):
    return c['level'], c['strain'], c['declarer'], c['doubled']


def label(c):
    return f"{c['level']}{'NT' if c['strain']=='N' else c['strain']}{['','X','XX'][c['doubled']]} {c['declarer']}"


def describe_contract(c, table, oracle_score):
    strain, seat = DD_STRAINS.index(c['strain']), SEATS.index(c['declarer'])
    tricks = table[strain][seat]
    return dict(level=c['level'], strain=c['strain'], declarer=c['declarer'],
                doubled=c['doubled'], label=label(c), dd_tricks=tricks,
                result_tricks=tricks - 6 - c['level'],
                score_ns=oracle_score(c['level'], strain, seat, tricks, c['doubled']))


def seats_for(auction):
    return [{'seat': SEATS[i % 4], 'call': call} for i, call in enumerate(auction)]


def export(run, out, source_dir):
    sys.path.insert(0, str(source_dir))
    import filter_deals as model
    from nt_choice import classify
    from test_continuation_par import oracle_score
    from audit_no_double_policy import replay, imps

    dataset = json.loads((run / 'deals.json').read_text())
    records = dataset['deals']
    rules = dataset['rules']
    dd = read_rows(run / 'dds.jsonl')
    results = {key: read_rows(run / name) for key, name in MODELS.items()}
    ids = [d['number'] for d in records]
    assert len(set(ids)) == len(ids) > 0
    assert set(ids) == set(dd)
    assert all(set(rows) == set(ids) for rows in results.values())
    assert dataset['dealer'] == 'N' and dataset['vulnerability'] == 'EW'
    raw_prefix = dataset['auction']
    prefix = list(map(normalize, raw_prefix))
    assert prefix == ['P', '1S', 'X', 'P', '1NT', '2H', 'P', '2S', 'P', 'P']
    source_files = ['deals.json', 'dds.jsonl', *MODELS.values()]
    before = {name: digest(run / name) for name in source_files}
    out.mkdir(parents=True, exist_ok=True)
    recorded, missing = {key: 0 for key in MODELS}, {key: [] for key in MODELS}
    pbn_chunks, csv_rows = [], []
    with (out / 'results.jsonl').open('w', encoding='utf-8') as stream:
        for d in records:
            board = d['number']
            pbn = 'N:' + ' '.join('.'.join(d['hands'][seat]['suits'][suit] for suit in SUITS) for seat in SEATS)
            assert dd[board]['pbn'] == pbn
            table = dd[board]['dd_table_CDHSN_NESW']
            assert len(table) == 5 and all(len(r) == 4 for r in table)
            assert all(type(t) is int and 0 <= t <= 13 for r in table for t in r)
            hands = {seat: model.Hand(tuple(d['hands'][seat]['suits'][s] for s in SUITS)) for seat in SEATS}
            seat_failures = {
                'N': model.north_failures(hands['N'], rules),
                'E': model.east_failures(hands['E'], rules),
                'S': [] if hands['S'].suits == model.FIXED_SOUTH else ['fixed_S'],
                'W': model.west_failures(hands['W'], rules),
            }
            failures = model.deal_failures(hands, rules)
            assert not failures and all(not fs for fs in seat_failures.values())
            filters = {seat: dict(passed=not fs, failures=fs) for seat, fs in seat_failures.items()}
            filters['all_passed'] = not failures
            filters['deal_integrity'] = dict(passed=True, failures=[], cards_each=13,
                                             unique_cards=52, total_hcp=40)
            baseline = results['original'][board]
            assert baseline['pbn'] == pbn
            pass_contract = describe_contract(dict(level=2, strain='S', declarer='E', doubled=0), table, oracle_score)
            assert pass_contract['score_ns'] == baseline['pass_score_ns']
            pass_auction = prefix + ['P']
            assert pass_auction[-3:] == ['P', 'P', 'P']
            pass_branch = dict(
                action='P', auction_status='model_defined_terminal_branch',
                auction_source='Specified Pass alternative: South passes and the auction ends.',
                full_auction=pass_auction, full_auction_with_seats=seats_for(pass_auction),
                contract=pass_contract, declarer='E', dd_tricks=pass_contract['dd_tricks'],
                score_ns=pass_contract['score_ns'], best_contract_unique=True,
                uniqueness_basis='Only the fixed East 2S undoubled terminal is defined in this branch.')
            double_branches = {}
            flat = dict(board=board, dealer='N', vulnerability='EW',
                        source_run=d.get('source_run'), source_number=d.get('source_number'),
                        source_shuffle_index=d.get('source_shuffle_index'),
                        north_passed=filters['N']['passed'], east_passed=filters['E']['passed'],
                        south_passed=filters['S']['passed'], west_passed=filters['W']['passed'],
                        pass_auction=' '.join(pass_auction), pass_contract='2S', pass_declarer='E',
                        pass_dd_tricks=pass_contract['dd_tricks'], pass_score_ns=pass_contract['score_ns'])
            for key, rows in results.items():
                r = rows[board]
                assert r['number'] == board and r['pbn'] == pbn
                assert r['pass_score_ns'] == pass_contract['score_ns']
                all_contracts = [describe_contract(c, table, oracle_score) for c in r['optimal_contracts']]
                assert all_contracts
                assert len({contract_key(c) for c in all_contracts}) == len(all_contracts)
                assert all(c['score_ns'] == r['double_par_score_ns'] for c in all_contracts)
                c = describe_contract(r['representative_contract'], table, oracle_score)
                assert c in all_contracts
                delta = r['double_par_score_ns'] - pass_contract['score_ns']
                assert delta == r['delta_ns']
                assert imps(delta) == r['delta_imp']
                bam = 1 if delta > 0 else 0 if delta < 0 else .5
                assert bam == r['bam_points']
                saved_line = r.get('representative_continuation')
                if isinstance(saved_line, list) and saved_line:
                    assert saved_line[-3:] == ['P', 'P', 'P'], (board, key, 'Recorded line does not end in three passes')
                    replay(r, table, r.get('blocked_ns_level3_strains', 0))
                    full = prefix + ['X'] + list(map(normalize, saved_line))
                    auction_status = 'recorded'
                    auction_source = 'recorded_search_principal_variation'
                    recorded[key] += 1
                else:
                    full = None
                    saved_line = None
                    auction_status = '未記錄'
                    auction_source = None
                    missing[key].append(board)
                branch = dict(
                    action='X', scenario=key, auction_status=auction_status,
                    auction_source=auction_source, raw_prefix_before_action=raw_prefix,
                    raw_recorded_continuation=saved_line,
                    full_auction=full, full_auction_with_seats=seats_for(full) if full else None,
                    contract=c, declarer=c['declarer'], dd_tricks=c['dd_tricks'], score_ns=c['score_ns'],
                    delta_score_ns=delta, delta_imp=r['delta_imp'], bam_points=bam,
                    bam_result='win' if delta > 0 else 'loss' if delta < 0 else 'tie',
                    optimal_contracts=all_contracts, optimal_contract_count=len(all_contracts),
                    best_contract_unique=len(all_contracts) == 1,
                    best_auction_unique=None, best_auction_unique_status='未記錄',
                    blocked_ns_level3_strains_mask_CDHS=r.get('blocked_ns_level3_strains', 0))
                double_branches[key] = branch
                flat.update({f'{key}_auction': ' '.join(full) if full else '未記錄',
                             f'{key}_contract': c['label'], f'{key}_declarer': c['declarer'],
                             f'{key}_dd_tricks': c['dd_tricks'], f'{key}_score_ns': c['score_ns'],
                             f'{key}_delta_imp': r['delta_imp'], f'{key}_bam_points': bam,
                             f'{key}_bam_result': branch['bam_result'],
                             f'{key}_best_contract_unique': branch['best_contract_unique'],
                             f'{key}_optimal_contract_count': len(all_contracts)})
            payload = dict(
                schema_version='1.0.0', board=board, dealer='N', vulnerability='EW',
                hands={seat: d['hands'][seat]['suits'] for seat in SEATS}, hand_metrics=d['hands'],
                pbn=pbn, handviewer_url=d['handviewer_url'],
                provenance=dict(source_run=d.get('source_run'), source_number=d.get('source_number'),
                                source_shuffle_index=d.get('source_shuffle_index'),
                                outcome_origin='reused_v6' if d.get('source_run') == 'run_v6_10000' else 'newly_solved_v7'),
                bidding_model_version=rules['model_version'], filters=filters,
                north_penalty_check=d['north_penalty_check'],
                north_1nt_minor_choice_check=classify(d['hands']['N']['suits']),
                auction_before_action=prefix, raw_auction_before_action=raw_prefix,
                dd_table=dict(strains=list(DD_STRAINS), seats=list(SEATS), tricks=table),
                pass_branch=pass_branch, double_branches=double_branches)
            stream.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
            csv_rows.append(flat)
            pbn_chunks.append('\n'.join([
                '[Event "Reopening double simulation DK v7"]', '[Site "Simulation"]',
                '[Date "????.??.??"]', f'[Board "{board}"]', '[West "Responder"]',
                '[North "Partner"]', '[East "Opener"]', '[South "You"]',
                '[Dealer "N"]', '[Vulnerable "EW"]', f'[Deal "{pbn}"]',
                '[Scoring "IMP/BAM"]', '[Declarer "?"]', '[Contract "?"]', '[Result "?"]', '']))
    (out / 'deals.pbn').write_text('\n'.join(pbn_chunks), encoding='utf-8')
    with (out / 'results.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
        writer.writeheader(); writer.writerows(csv_rows)
    write_schema(out)
    after = {name: digest(run / name) for name in source_files}
    assert before == after, 'Raw inputs were modified while exporting'
    audit = dict(status='passed', boards=len(records), pbn_boards=len(pbn_chunks),
                 per_seat_filter_checks=4 * len(records), recorded_search_auctions=recorded,
                 missing_search_auctions=missing,
                 all_recorded_search_auctions_legally_replayed_and_end_in_three_passes=True,
                 no_search_auction_synthesized=True, no_DDS_or_Par_recomputed=True,
                 raw_input_sha256=before,
                 output_sha256={name: digest(out / name) for name in ['deals.pbn', 'results.jsonl', 'results.csv', 'schema.json']})
    (out / 'export_validation.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(audit, ensure_ascii=False, indent=2))


def write_schema(out):
    definitions = {
        'schema_version': '1.0.0',
        'format': 'JSON Lines, one object per final accepted board; CSV is a flat companion view.',
        'primary_key': 'board',
        'pbn': 'PBN Deal tag syntax, starting with N and hands in N E S W order; suit order S H D C.',
        'vulnerability': 'EW: East-West vulnerable, North-South not vulnerable.',
        'filters': 'Per-seat passed/failures use the v7 cards-only pre-decision bidding filters. S checks fixed South; deal_integrity also checks all 52 cards. No DD/Par outcome enters acceptance.',
        'hand_metrics': 'Saved suits, HCP, shape_SHDC, balanced flag and basic losing-trick count for each seat.',
        'raw_auction_before_action': 'Exactly the saved dataset prefix; D means double and 1N means 1NT.',
        'full_auction': 'Normalized display tokens, starting at N: P, X, XX, or level plus C/D/H/S/NT. No AP abbreviation. Every recorded final line ends P P P.',
        'full_auction_with_seats': 'Same complete auction with N/E/S/W assigned cyclically from dealer N.',
        'pass_branch': 'South Pass is the specified terminal alternative; existing N and E passes plus this Pass terminate East 2S undoubled. It is a defined model branch, not a searched or observed auction.',
        'double_branches': {
            'original': 'Exact perfect-information, history-constrained continuation Par after South X; West next, all four seats free to bid.',
            'protect_32': 'Same search, prohibit EW double of NS level-three suit contracts with exactly eight NS trumps and EW 3-2 split.',
            'protect_32_41': 'Same protection also for EW 4-1 split; 5-0 unprotected.',
            'policy_scope': 'Both NS declarers, all four suit strains, throughout the continuation. Does not protect 3NT or other levels. This is search legality, not a player-response heuristic.',
        },
        'auction_source': 'recorded_search_principal_variation means prefix + South X + the exact saved representative_continuation, with token spelling normalization only. If absent, status is 未記錄 and full_auction is null; no substitute continuation is generated.',
        'representative_selection': 'One search-returned optimal principal variation; not an estimated human-choice probability. Other equally optimal contracts are retained without invented auctions.',
        'contract': {'level': '1..7', 'strain': 'C,D,H,S,N (N means notrump)',
                     'declarer': 'N,E,S,W', 'doubled': '0=undoubled,1=doubled,2=redoubled',
                     'dd_tricks': 'Declarer-side best-play tricks, including best opening lead.',
                     'result_tricks': 'dd_tricks minus contract target (6+level).',
                     'score_ns': 'Duplicate score from North-South viewpoint.'},
        'dd_table': '20 saved DD values; rows CDHSN and columns NESW.',
        'delta_score_ns': 'Double branch score_ns minus Pass branch score_ns.',
        'delta_imp': 'Each paired score difference converted by the standard IMP table; positive favors Double.',
        'bam_points': 'Raw-score win=1, tie=0.5, loss=0, comparing Double to Pass. Not an actual field matchpoint percentage.',
        'best_contract_unique': 'True iff the saved optimal terminal contract set contains exactly one (level,strain,declarer,doubled) tuple. Declarer distinctions count. Does not imply a unique auction.',
        'best_auction_unique': 'Null: the search did not record an exhaustive count of optimal auction paths. best_auction_unique_status is 未記錄.',
        'provenance': 'Final board numbers 1..10000; source_number retains original v6 ID or supplemental ID. source_shuffle_index is recorded for new supplemental boards only, otherwise null.',
        'source_versions': 'Current filters version 7; inherited v6 retained outcomes have identical DDS, score and continuation-search models. Source versions and hashes are in package metadata and raw records.',
    }
    (out / 'schema.json').write_text(json.dumps(definitions, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('output_data_dir', type=Path)
    parser.add_argument('--source-dir', type=Path, default=Path(__file__).resolve().parent / 'current',
                        help='Current model modules; defaults to package source/current.')
    args = parser.parse_args()
    export(args.run_dir.resolve(), args.output_data_dir.resolve(), args.source_dir.resolve())


if __name__ == '__main__':
    main()
