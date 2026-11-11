"""Merge unchanged retained outcomes with the newly solved supplement."""
import hashlib
import json
from pathlib import Path

from dds_backend import pbn

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / 'run_v6_10000'
FILES = ['dds.jsonl', 'results.jsonl', 'no_double_policy/protect_32.jsonl',
         'no_double_policy/protect_32_41.jsonl']


def read(path):
    return {r['number']: r for r in map(json.loads, path.read_text().splitlines())}


def main():
    deals = json.loads((ROOT / 'deals.json').read_text())['deals']
    assert len(deals) == 10000
    for name in FILES:
        assert not (ROOT / name).exists(), f'Refusing to overwrite {name}'
        original, supplement = read(OLD / name), read(ROOT / 'supplement' / name)
        assert len(supplement) == 872
        with (ROOT / name).open('w') as stream:
            for d in deals:
                row = dict(original[d['source_number']] if d['source_run'] == 'run_v6_10000'
                           else supplement[d['number']])
                row['number'] = d['number']
                assert row['pbn'] == pbn(d)
                stream.write(json.dumps(row) + '\n')
    snapshot = json.loads((ROOT / 'source_snapshot.json').read_text())
    assert all(hashlib.sha256((OLD / name).read_bytes()).hexdigest() == digest for name, digest in snapshot.items())
    print('Merged 9,128 saved rows and 872 new rows for all four caches; original source hashes unchanged.')


if __name__ == '__main__':
    main()
