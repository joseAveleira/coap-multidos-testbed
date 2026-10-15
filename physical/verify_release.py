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
summary = json.loads((data / 'resumen_verificado_v3.json').read_text())
manifest = json.loads((data / 'sesiones_v3_manifest.json').read_text())
assert len(manifest['sessions']) == 8
for session in manifest['sessions']:
    assert (data / session['pcap']).is_file(), session['session']
    if 'actor' in session:
        assert (data / session['actor']['directory']).is_dir()
        assert (data / session['actor']['clock_file']).is_file()

for window, expected in summary['physical_exports'].items():
    path = data / 'dataset_v3' / window / 'dataset_clean_multiclass.csv'
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

# Verify the separate five-capture package as well.
main = json.loads((data / 'campana_30_manifest.json').read_text())
assert len(main['sessions']) == 5
assert summary['campaign_attack_episodes'] == {'block2_amplification': 30, 'request_flood': 30}
for width, expected in summary['campaign_exports'].items():
    with (data / 'campana_30_csv' / width / 'dataset_clean_multiclass.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == expected['rows']
    assert dict(Counter(r['target'] for r in rows)) == expected['classes']
    assert {r['meta_session'] for r in rows} == {s['session'] for s in main['sessions']}
print('Five main captures and 30 episodes of each attack verified.')
