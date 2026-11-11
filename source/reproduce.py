#!/usr/bin/env python3
"""Portable verification, seed replay, and complete DK v7 reproduction.

Use the pinned requirements in source/requirements.txt and a C++17 compiler.
Modes never overwrite the reference package. Full mode builds native Par
libraries inside the newly created output directory, not inside the package.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib
from importlib.metadata import distribution, version
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
PACKAGE = Path(__file__).resolve().parents[1]
OUTCOME_FILES = ['results.jsonl', 'no_double_policy/protect_32.jsonl',
                 'no_double_policy/protect_32_41.jsonl']
SEMANTIC_FIELDS = ['number', 'pbn', 'handviewer_url', 'east_2S_tricks',
                   'pass_score_ns', 'double_par_score_ns', 'delta_ns',
                   'delta_imp', 'bam_points', 'representative_continuation',
                   'representative_contract']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pbn(deal):
    return 'N:' + ' '.join('.'.join(deal['hands'][seat]['suits'][suit] for suit in 'SHDC')
                           for seat in 'NESW')


def contracts(row):
    return {(c['level'], c['strain'], c['declarer'], c['doubled']) for c in row['optimal_contracts']}


def run_script(script, arguments, log):
    command = [sys.executable, '-B', str(script), *map(str, arguments)]
    with Path(log).open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', bufsize=1)
        assert process.stdout is not None
        for line in process.stdout:
            stream.write(line)
            stream.flush()
            if line.startswith(('Shuffles ', 'DDS ', 'Continuation Par ', 'protect_32 ', 'protect_32_41 ', 'Accepted ')):
                print(line.rstrip(), flush=True)
        code = process.wait()
    if code:
        raise RuntimeError(f'{Path(script).name} exited {code}; see {log}')


def compare_deals(reference, candidate):
    expected, actual = read(reference / 'deals.json'), read(candidate / 'deals.json')
    assert expected['seed'] == actual['seed'], 'Seed differs'
    assert expected['attempts'] == actual['attempts'], 'Shuffle endpoint differs'
    assert expected['rules'] == actual['rules'], 'Bidding rules differ'
    assert len(expected['deals']) == len(actual['deals']) == 10000
    for old, new in zip(expected['deals'], actual['deals']):
        assert old['number'] == new['number'], 'Board order differs'
        for key in ['hands', 'north_penalty_check', 'handviewer_url']:
            assert old[key] == new[key], (old['number'], key)
    canonical = '\n'.join(pbn(d) for d in actual['deals']) + '\n'
    return dict(status='passed', seed=actual['seed'], accepted_count=10000,
                random_shuffles=actual['attempts'],
                compared_fields=['board number', 'all hands and diagnostics', 'north penalty diagnostic', 'Handviewer'],
                reference_provenance_fields_intentionally_not_compared=True,
                canonical_PBN_sha256=hashlib.sha256(canonical.encode()).hexdigest())


def compare_outcomes(reference, candidate):
    old_dd, new_dd = jsonl(reference / 'dds.jsonl'), jsonl(candidate / 'dds.jsonl')
    assert len(old_dd) == len(new_dd) == 10000
    assert old_dd == new_dd, 'DDS table differs'
    report = {'status': 'passed', 'DDS_tables_equal': 10000, 'scenarios': {}}
    for name in OUTCOME_FILES:
        old, new = jsonl(reference / name), jsonl(candidate / name)
        assert len(old) == len(new) == 10000
        for a, b in zip(old, new):
            for key in SEMANTIC_FIELDS:
                assert a[key] == b[key], (name, a['number'], key)
            assert contracts(a) == contracts(b), (name, a['number'], 'optimal contract set')
            for key in ['blocked_ns_level3_strains', 'original_par_score_ns', 'original_delta_imp']:
                if key in a:
                    assert a[key] == b[key], (name, a['number'], key)
        report['scenarios'][name] = dict(rows=10000, all_scores_and_imp_bam_equal=True,
                                        optimal_terminal_sets_equal=True,
                                        actual_saved_continuations_equal=True,
                                        solver_timing_and_nodes_not_compared=True)
    return report


def native_runtime():
    if shutil.which('g++') is None:
        raise RuntimeError('Full reproduction requires g++ with C++17 support')
    path = distribution('endplay').locate_file('endplay/_dds/libdds.so')
    lib = ctypes.CDLL(str(path))
    lib.SetMaxThreads.argtypes = [ctypes.c_int]
    lib.SetMaxThreads.restype = None
    lib.SetMaxThreads(1)
    # Oversized buffer avoids the older endplay DDSInfo structure definition.
    lib.GetDDSInfo.argtypes = [ctypes.c_void_p]
    lib.GetDDSInfo.restype = None
    info = ctypes.create_string_buffer(8192)
    lib.GetDDSInfo(info)
    native = tuple((ctypes.c_int * 3).from_buffer(info))
    assert native == (2, 9, 0), f'Expected DDS 2.9.0, found {native}'
    assert version('endplay') == '0.5.12', 'Use the pinned endplay version'
    return dict(DDS='.'.join(map(str, native)), endplay=version('endplay'),
                numpy=version('numpy'), native_library_sha256=digest(path))


def align_bootstrap(reference, candidate, sources):
    """Use the final saved run's seeds, instead of historical CLI defaults."""
    sys.path.insert(0, str(sources))
    experiment = importlib.import_module('run_experiment')
    policy = importlib.import_module('run_dk_no_double_policy')
    expected = read(reference / 'summary.json')
    base = read(candidate / 'summary.json')
    models = [jsonl(candidate / name) for name in OUTCOME_FILES]
    base.update(experiment.statistics(models[0], expected['bootstrap_replicates'], expected['bootstrap_seed']))
    write(candidate / 'summary.json', base)
    for key in ['mean_imp_bootstrap_95', 'bam_mean_points_bootstrap_95', 'mean_raw_delta_bootstrap_95']:
        assert base[key] == expected[key], ('baseline bootstrap', key)
    saved_policy = read(reference / 'no_double_policy/summary.json')
    actual_policy = read(candidate / 'no_double_policy/summary.json')
    boot = saved_policy['bootstrap']
    actual_policy['bootstrap'] = policy.bootstrap(models, boot['replicates'], boot['seed'])
    assert actual_policy['bootstrap'] == boot, 'Policy bootstrap differs'
    write(candidate / 'no_double_policy/summary.json', actual_policy)
    return dict(status='passed', baseline_seed=expected['bootstrap_seed'],
                policy_seed=boot['seed'], replicates=boot['replicates'],
                saved_confidence_intervals_equal=True)


def verify_manifest(package):
    manifest = package / 'MANIFEST.sha256'
    if not manifest.is_file():
        raise FileNotFoundError(f'Missing {manifest}; this verifies a completed package')
    checked = set()
    for line in manifest.read_text().splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        relative = relative.lstrip('*')
        target = (package / relative).resolve()
        assert target.is_relative_to(package.resolve()), 'Manifest path escapes package'
        assert target.is_file(), f'Missing {relative}'
        assert digest(target) == expected, f'Checksum mismatch: {relative}'
        assert relative not in checked, f'Duplicate manifest entry: {relative}'
        checked.add(relative)
    for path in package.rglob('*'):
        if path.is_file():
            assert not path.name.startswith('._'), f'AppleDouble file: {path}'
    return dict(status='passed', files_checked=len(checked))


def verify_cached(reference, sources):
    sys.path.insert(0, str(sources))
    model = importlib.import_module('filter_deals')
    oracle = importlib.import_module('test_continuation_par')
    policy = importlib.import_module('audit_no_double_policy')
    saved = read(reference / 'deals.json')
    deals, dd = saved['deals'], jsonl(reference / 'dds.jsonl')
    assert len(deals) == len(dd) == 10000
    assert len({pbn(d) for d in deals}) == 10000
    for index, (deal, table) in enumerate(zip(deals, dd), 1):
        assert deal['number'] == table['number'] == index
        assert pbn(deal) == table['pbn']
        hands = {s: model.Hand(tuple(deal['hands'][s]['suits'][u] for u in 'SHDC')) for s in 'NESW'}
        assert not model.deal_failures(hands, saved['rules']), index
    baseline = jsonl(reference / 'results.jsonl')
    policies = [jsonl(reference / name) for name in OUTCOME_FILES[1:]]
    totals = {}
    for key, rows, policy_key in zip(OUTCOME_FILES, [baseline, *policies], [None, 'A', 'B']):
        assert len(rows) == 10000
        count = 0
        for deal, table_record, original, row in zip(deals, dd, baseline, rows):
            n = deal['number']
            assert n == row['number'] and row['pbn'] == table_record['pbn']
            table = table_record['dd_table_CDHSN_NESW']
            assert row['east_2S_tricks'] == table[3][1]
            assert row['pass_score_ns'] == oracle.oracle_score(2, 3, 1, table[3][1])
            delta = row['double_par_score_ns'] - row['pass_score_ns']
            assert row['delta_ns'] == delta
            assert row['delta_imp'] == policy.imps(delta)
            assert row['bam_points'] == (1 if delta > 0 else 0 if delta < 0 else .5)
            mask = policy.mask_for(row['pbn'], policy_key) if policy_key else 0
            if policy_key:
                assert row['blocked_ns_level3_strains'] == mask
                assert row['double_par_score_ns'] >= original['double_par_score_ns']
            terminal_set = contracts(row)
            assert terminal_set and len(terminal_set) == len(row['optimal_contracts'])
            for level, strain, seat, doubled in terminal_set:
                i, j = 'CDHSN'.index(strain), 'NESW'.index(seat)
                assert oracle.oracle_score(level, i, j, table[i][j], doubled) == row['double_par_score_ns']
                assert not (level == 3 and seat in 'NS' and doubled and strain in 'CDHS' and mask & (1 << i))
            policy.replay(row, table, mask)
            assert row['representative_continuation'][-3:] == ['P', 'P', 'P']
            count += len(terminal_set)
        totals[key] = dict(rows=10000, legal_complete_auctions=10000,
                           independently_scored_terminals=count,
                           mean_imp=sum(r['delta_imp'] for r in rows) / 10000,
                           bam=sum(r['bam_points'] for r in rows) / 10000)
    for a, b in zip(*policies):
        assert b['double_par_score_ns'] >= a['double_par_score_ns']
    return dict(status='passed', boards=10000, all_v7_filters_pass=True,
                scenarios=totals, dds_or_par_recomputed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['verify', 'sample', 'full'], default='verify')
    parser.add_argument('--output', type=Path, help='New output directory; must not exist')
    parser.add_argument('--dds-threads', type=int, default=4)
    parser.add_argument('--source-dir', type=Path, default=PACKAGE / 'source/current',
                        help='Optional alternate frozen source tree')
    parser.add_argument('--reference', type=Path, default=PACKAGE / 'data/raw/current',
                        help='Optional alternate saved raw run')
    args = parser.parse_args()
    sources, reference = args.source_dir.resolve(), args.reference.resolve()
    start = time.monotonic()
    if args.output:
        output = args.output.resolve()
        if output.exists():
            parser.error('--output must be a new directory')
        if output.is_relative_to(PACKAGE.resolve()):
            parser.error('--output must be outside the sealed package directory')
        if output.is_relative_to(reference):
            parser.error('--output must be outside reference data')
        output.mkdir(parents=True)
    else:
        output = None
    if args.mode in ['sample', 'full'] and output is None:
        parser.error('--output is required for sample/full')
    report = dict(mode=args.mode, python_version=platform.python_version(),
                  executed_at_utc=datetime.now(timezone.utc).isoformat())
    if args.mode == 'verify':
        verifier = PACKAGE / 'source/verify_package.py'
        if verifier.is_file():
            result = subprocess.run([sys.executable, '-B', str(verifier), '--package-root', str(PACKAGE)],
                                    check=True, capture_output=True, text=True, encoding='utf-8')
            report['package_validation'] = json.loads(result.stdout)
        else:
            report['manifest'] = verify_manifest(PACKAGE)
            report['cached_data'] = verify_cached(reference, sources)
    else:
        assert output is not None
        if args.mode == 'full':
            report['native_runtime'] = native_runtime()
        work_sources = output / 'model_sources'
        shutil.copytree(sources, work_sources,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.so', '._*', '.DS_Store'))
        saved = read(reference / 'deals.json')
        run_script(work_sources / 'filter_deals.py',
                   ['--count', len(saved['deals']), '--seed', saved['seed'],
                    '--max-attempts', saved['attempts'], '--rules', work_sources / 'rules.json',
                    '--output-dir', output, '--progress-every', 1_000_000], output / 'generation.log')
        report['seed_replay'] = compare_deals(reference, output)
        write(output / 'seed_replay_validation.json', report['seed_replay'])
        if args.mode == 'full':
            run_script(work_sources / 'run_experiment.py',
                       [output, '--dds-threads', args.dds_threads, '--bootstrap-count', 10000], output / 'experiment.log')
            run_script(work_sources / 'run_dk_no_double_policy.py',
                       [output, '--bootstrap', 10000], output / 'no_double_policy.log')
            report['outcome_replay'] = compare_outcomes(reference, output)
            write(output / 'outcome_replay_validation.json', report['outcome_replay'])
            report['bootstrap_replay'] = align_bootstrap(reference, output, work_sources)
            run_script(work_sources / 'audit_final_results.py', [output], output / 'final_audit.log')
            run_script(work_sources / 'audit_no_double_policy.py',
                       [output, '--scenario-a', output / OUTCOME_FILES[1],
                        '--scenario-b', output / OUTCOME_FILES[2],
                        '--output', output / 'no_double_policy/validation.json'], output / 'policy_audit.log')
            exporter = PACKAGE / 'source/export_data.py'
            if exporter.is_file():
                run_script(exporter, [output, output / 'exported'], output / 'export.log')
                report['normalized_export'] = 'exported/'
    report['elapsed_seconds'] = time.monotonic() - start
    report['status'] = 'passed'
    if output:
        write(output / 'reproduction_audit.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
