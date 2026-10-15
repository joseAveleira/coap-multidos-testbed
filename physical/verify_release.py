"""Verify published evidence bytes, session paths and clean CSV class counts."""
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
inventory = json.loads((ROOT / 'FILES.json').read_text())
for item in inventory['files']:
    path = ROOT / item['path']
    assert path.is_file(), item['path']
    assert path.stat().st_size == item['bytes'], item['path']
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert digest == item['sha256'], item['path']

data = ROOT / 'recursos/dataset_fisico'
summary = json.loads((data / 'resumen_verificado_v2.json').read_text())
manifest = json.loads((data / 'sesiones_v2_manifest.json').read_text())
assert len(manifest['sessions']) == 7
for session in manifest['sessions']:
    assert (data / session['pcap']).is_file(), session['session']
    if 'actor' in session:
        assert (data / session['actor']['directory']).is_dir()
        assert (data / session['actor']['clock_file']).is_file()

for window, expected in summary['physical_exports'].items():
    path = data / 'dataset_v2' / window / 'dataset_clean_multiclass.csv'
    counts, sessions = Counter(), set()
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        assert len(reader.fieldnames) == 25
        predictors = [name for name in reader.fieldnames if name not in {'meta_session', 'target'}]
        assert len(predictors) == 23
        for row in reader:
            counts[row['target']] += 1
            sessions.add(row['meta_session'])
            assert all(math.isfinite(float(row[name])) for name in predictors)
    assert dict(counts) == expected['classes'], (window, counts)
    assert sum(counts.values()) == expected['rows']
    assert sessions == {session['session'] for session in manifest['sessions']}
print(json.dumps({'verified_files': len(inventory['files']), 'physical_sessions': len(manifest['sessions']),
                  'clean_csv_counts': summary['physical_exports'], 'finite_predictors': True}, indent=2))
