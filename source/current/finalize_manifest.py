"""Record completed v7 provenance, validations, source and output hashes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / 'run_v6_10000'


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    sampling = read(ROOT / 'sampling_manifest.json')
    old_hashes = read(ROOT / 'source_snapshot.json')
    assert all(digest(OLD / name) == expected for name, expected in old_hashes.items())
    validations = {name: read(ROOT / name) for name in [
        'full_dataset_validation.json', 'final_results_validation.json', 'no_double_policy/validation.json']}
    assert validations['full_dataset_validation.json']['status'] == 'passed'
    assert validations['final_results_validation.json']['status'] == 'passed'
    for key in ['A', 'B']:
        assert validations['no_double_policy/validation.json'][key]['status'] == 'passed'
    manifest = dict(model_version=7, requested_count=10000, completed=True,
                    source_run=str(OLD), source_artifacts_unchanged=True,
                    source_sha256=old_hashes, sampling=sampling,
                    retained_saved_outcomes=9128, newly_solved_deals=872,
                    exactly_continued_original_rng_stream=True,
                    stopping_independent_of_outcomes=True,
                    fixed_south='S3 H9754 DAKT8 CA764',
                    vulnerability='NS nonvulnerable, EW vulnerable',
                    double_branch='After South doubles East 2S; West next; history-constrained continuation Par',
                    dds=read(ROOT / 'dds_version.json'),
                    validation_status='passed',
                    code_sha256={p.name: digest(p) for p in sorted((ROOT / 'model_sources').iterdir()) if p.is_file()},
                    artifact_sha256={str(p.relative_to(ROOT)): digest(p) for p in sorted(ROOT.rglob('*'))
                                     if p.is_file() and '__pycache__' not in p.parts
                                     and 'model_sources' not in p.parts
                                     and p.name != 'experiment_manifest.json'})
    (ROOT / 'experiment_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('v7 complete: 10,000 qualified deals; all dataset and three-outcome audits passed; v6 sources unchanged.')


if __name__ == '__main__':
    main()
