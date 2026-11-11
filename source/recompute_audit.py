#!/usr/bin/env python3
"""Recompute a deterministic, outcome-blind sample of DDS and all three Pars.

The two C++ Par libraries are rebuilt in a temporary directory from source;
no packaged shared library is loaded or modified. Saved input files are read
only. Run from a package with source/current and data/raw/current, or supply
--run-dir and --source-dir explicitly.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time


SCENARIOS = {
    'original': 'results.jsonl',
    'protect_32': 'no_double_policy/protect_32.jsonl',
    'protect_32_41': 'no_double_policy/protect_32_41.jsonl',
}
BUILD_FILES = ['continuation_par.py', 'continuation_par.cpp',
               'continuation_par_policy.py', 'continuation_par_policy.cpp',
               'dds_backend.py', 'test_continuation_par.py',
               'audit_no_double_policy.py']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    result = {r['number']: r for r in rows}
    assert len(result) == len(rows), ('duplicate board ID', str(path))
    return result


def contract_set(contracts):
    return sorted((c['level'], c['strain'], c['declarer'], c['doubled']) for c in contracts)


def main():
    package = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir', type=Path, default=package / 'data/raw/current')
    ap.add_argument('--source-dir', type=Path, default=Path(__file__).resolve().parent / 'current')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--seed', type=int, default=2026111114)
    ap.add_argument('--per-cohort', type=int, default=20)
    ap.add_argument('--dds-threads', type=int, default=2)
    args = ap.parse_args()
    assert args.per_cohort > 0
    run, source = args.run_dir.resolve(), args.source_dir.resolve()
    started = time.monotonic()
    dataset = json.loads((run / 'deals.json').read_text())
    records = dataset['deals']

    # Fix the selected IDs from provenance only, before reading outcomes.
    retained = [r['number'] for r in records if r.get('source_run') == 'run_v6_10000']
    added = [r['number'] for r in records if r.get('source_run') == 'v7_supplement']
    assert len(retained) == 9128 and len(added) == 872
    rng = random.Random(args.seed)
    selected_retained = sorted(rng.sample(retained, args.per_cohort))
    selected_added = sorted(rng.sample(added, args.per_cohort))
    selected = sorted(selected_retained + selected_added)
    selected_set = set(selected)
    assert len(selected_set) == 2 * args.per_cohort
    inputs = ['deals.json', 'dds.jsonl', *SCENARIOS.values()]
    input_hashes = {name: digest(run / name) for name in inputs}
    source_hashes = {name: digest(source / name) for name in BUILD_FILES}
    dd = read_rows(run / 'dds.jsonl')
    outcomes = {name: read_rows(run / file) for name, file in SCENARIOS.items()}
    deals = {r['number']: r for r in records}
    details = []

    with tempfile.TemporaryDirectory(prefix='bridge-dds-par-audit-') as temporary:
        work = Path(temporary)
        for name in BUILD_FILES:
            shutil.copy2(source / name, work / name)
        assert not list(work.glob('*.so'))
        sys.path.insert(0, str(work))
        backend = importlib.import_module('dds_backend')
        original_solver = importlib.import_module('continuation_par')
        policy_solver = importlib.import_module('continuation_par_policy')
        audit = importlib.import_module('audit_no_double_policy')
        oracle = importlib.import_module('test_continuation_par')
        engine = backend.DDS(args.dds_threads)
        version_buffer = ctypes.create_string_buffer(8192)
        engine.lib.GetDDSInfo.argtypes = [ctypes.c_void_p]
        engine.lib.GetDDSInfo.restype = None
        engine.lib.GetDDSInfo(version_buffer)
        native_version = '.'.join(map(str, (ctypes.c_int * 3).from_buffer(version_buffer)))
        assert native_version == '2.9.0', ('Unexpected DDS version', native_version)
        pbns = [backend.pbn(deals[n]) for n in selected]
        actual_tables = []
        for i in range(0, len(pbns), 20):
            actual_tables.extend(engine.tables(pbns[i:i + 20]))

        for number, pbn, actual_table in zip(selected, pbns, actual_tables):
            expected_table = dd[number]['dd_table_CDHSN_NESW']
            assert dd[number]['pbn'] == pbn
            assert actual_table == expected_table, ('DDS disagreement', number)
            board = dict(number=number,
                         cohort='retained' if number in selected_retained else 'supplement',
                         pbn=pbn, expected_dd_table_CDHSN_NESW=expected_table,
                         actual_dd_table_CDHSN_NESW=actual_table, dds_equal=True,
                         scenarios={})
            for name in SCENARIOS:
                saved = outcomes[name][number]
                assert saved['pbn'] == pbn
                mask = 0 if name == 'original' else audit.mask_for(pbn, 'A' if name == 'protect_32' else 'B')
                if name == 'original':
                    actual = original_solver.solve(actual_table, want_pv=True, want_all=True)
                else:
                    actual = policy_solver.solve(actual_table, want_pv=True, want_all=True,
                                                 blocked_ns_level3_strains=mask)
                score_equal = actual['score_ns'] == saved['double_par_score_ns']
                contracts_equal = contract_set(actual['optimal_contracts']) == contract_set(saved['optimal_contracts'])
                pv_equal = actual['auction'] == saved['representative_continuation']
                representative_equal = actual['contract'] == saved['representative_contract']
                assert score_equal and contracts_equal and pv_equal and representative_equal, (number, name)
                assert saved['representative_continuation'][-3:] == ['P', 'P', 'P']
                saved_calls = audit.replay(saved, expected_table, mask)
                actual_row = dict(number=number, representative_continuation=actual['auction'],
                                  representative_contract=actual['contract'], double_par_score_ns=actual['score_ns'])
                replayed_calls = audit.replay(actual_row, actual_table, mask)
                pass_score = oracle.oracle_score(2, 3, 1, actual_table[3][1])
                assert pass_score == saved['pass_score_ns']
                assert audit.imps(actual['score_ns'] - pass_score) == saved['delta_imp']
                for contract in actual['optimal_contracts']:
                    s, d = 'CDHSN'.index(contract['strain']), 'NESW'.index(contract['declarer'])
                    assert oracle.oracle_score(contract['level'], s, d, actual_table[s][d],
                                               contract['doubled']) == actual['score_ns']
                board['scenarios'][name] = dict(
                    mask=mask, expected_score_ns=saved['double_par_score_ns'], actual_score_ns=actual['score_ns'],
                    score_equal=score_equal, expected_optimal_contracts=saved['optimal_contracts'],
                    actual_optimal_contracts=actual['optimal_contracts'], optimal_contract_sets_equal=contracts_equal,
                    expected_recorded_continuation=saved['representative_continuation'],
                    actual_continuation=actual['auction'], recorded_continuation_equal=pv_equal,
                    representative_contract_equal=representative_equal,
                    saved_pv_legally_replayed_calls=saved_calls, actual_pv_legally_replayed_calls=replayed_calls,
                    all_optimal_contracts_independently_scored=True,
                    pass_score_and_imp_independently_recomputed=True)
            details.append(board)
        built_libraries = ['libcontinuation_par.so', 'libcontinuation_par_policy.so']
        assert all((work / name).is_file() for name in built_libraries)
        build = dict(rebuilt_from_cpp_in_fresh_temporary_directory=True,
                     packaged_shared_libraries_loaded=False,
                     compiler=subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
                     commands=['g++ -O3 -std=c++17 -shared -fPIC continuation_par.cpp -o libcontinuation_par.so',
                               'g++ -O3 -std=c++17 -shared -fPIC continuation_par_policy.cpp -o libcontinuation_par_policy.so'],
                     binary_sha256={name: digest(work / name) for name in built_libraries})
        dds_info = dict(native_version=native_version, endplay_version=engine.endplay_version,
                        library_sha256=digest(Path(engine.library_path)), threads=args.dds_threads,
                        entrypoint='CalcAllTablesPBN', batch_size=20)
    assert input_hashes == {name: digest(run / name) for name in inputs}
    assert source_hashes == {name: digest(source / name) for name in BUILD_FILES}
    report = dict(status='passed', timestamp_utc=datetime.now(timezone.utc).isoformat(),
                  python_version=platform.python_version(), sample_seed=args.seed,
                  selection_method=f'{args.per_cohort} retained and {args.per_cohort} supplement IDs sampled without replacement from provenance before reading outcomes',
                  selected_retained=selected_retained, selected_supplement=selected_added,
                  selected_count=len(selected), dds_tables_recomputed=len(selected),
                  dds_trick_entries_compared=len(selected) * 20,
                  par_searches_recomputed=len(selected) * 3,
                  all_dds_entries_equal=True, all_par_scores_equal=True,
                  all_optimal_contract_sets_equal=True, all_recorded_principal_variations_equal=True,
                  source_inputs_unchanged=True, input_sha256=input_hashes,
                  source_code_sha256=source_hashes, dds=dds_info, cpp_rebuild=build,
                  elapsed_seconds=time.monotonic() - started, boards=details,
                  scope='Partial deterministic recheck, not a full independent double-dummy or minimax implementation.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ['status', 'selected_count', 'dds_tables_recomputed',
                                           'par_searches_recomputed', 'elapsed_seconds']}, indent=2))


if __name__ == '__main__':
    main()
