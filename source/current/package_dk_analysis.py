#!/usr/bin/env python3
"""Bundle the DK descriptive report, saved inputs and analysis scripts."""
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
run = root / 'run_v5_10000'
output = root / 'dk_analysis_latest_10000.zip'
scripts = ['analyze_dk_contracts.py', 'analyze_dk_factors.py',
           'analyze_dk_heart_components.py', 'heart_strength_analysis.py',
           'render_dk_analysis.py']
sources = ['deals.json', 'results.jsonl', 'dds.jsonl', 'summary.json',
           'experiment_manifest.json', 'model_sources/rules.json',
           'full_dataset_validation.json', 'final_results_validation.json']
analysis = run / 'contract_analysis'
assert (analysis / 'report.pdf').read_bytes().rstrip().endswith(b'%%EOF')
validation = json.loads((analysis / 'render_validation.json').read_text())
assert validation['pdf_pages'] == 7
assert all(not c['overflow_errors'] for c in validation['checks'])
files = [(root / s, 'scripts/' + s) for s in scripts]
files += [(run / s, 'source_run/' + s) for s in sources]
files += [(f, 'source_run/contract_analysis/' + f.name) for f in sorted(analysis.iterdir()) if f.is_file()]
manifest = dict(
    dataset='Latest DK run, mean Double-minus-Pass IMP = +0.4889',
    n=10000, no_simulation_rerun=True,
    files={name:sha256(path.read_bytes()).hexdigest() for path,name in files},
    packages={p:importlib.metadata.version(p) for p in ['numpy','scipy','matplotlib']},
    font='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
with ZipFile(output, 'w', ZIP_DEFLATED, compresslevel=6) as z:
    for path, name in files:
        z.write(path, name)
    z.writestr('README.txt', (analysis / 'README.txt').read_bytes())
    z.writestr('bundle_manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
with ZipFile(output) as z:
    assert z.testzip() is None
    for path, name in files:
        assert sha256(z.read(name)).hexdigest() == manifest['files'][name]
print(json.dumps(dict(path=str(output), bytes=output.stat().st_size,
                     member_files=len(files)+2, sha256=sha256(output.read_bytes()).hexdigest()), indent=2))
