"""Audit request coverage for every observed physical client in a campaign."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


def audit(campaign_path, exports, output):
    campaign_path, exports, output = Path(campaign_path), Path(exports), Path(output)
    targets = [output.with_suffix('.csv'), output.with_suffix('.json')]
    if any(p.exists() for p in targets):
        raise FileExistsError('Use a new output prefix; existing evidence is not overwritten')
    state = json.loads(campaign_path.read_text(encoding='utf-8'))
    if state['status'] != 'captured_pending_extraction':
        raise ValueError('A completed campaign is required')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    sources = {str(campaign_path.resolve()): sha(campaign_path)}
    rows = []
    for record in state['sessions']:
        if record['status'] != 'captured_pending_extraction':
            raise ValueError('Campaign includes an incomplete capture')
        name, devices = record['session'], record['devices_observed_in_campaign']
        observed = {d['observed_ipv4']: [] for d in devices}
        first, last = float('inf'), float('-inf')
        path = exports / name / 'packet_extract' / f'{name}.tsv'
        sources[str(path.resolve())] = sha(path)
        for frame in pd.read_csv(path, sep='\t', usecols=['frame.time_epoch', 'ip.src', 'coap.code'], chunksize=50000):
            first = min(first, frame['frame.time_epoch'].min())
            last = max(last, frame['frame.time_epoch'].max())
            requests = frame[frame['coap.code'] == 1]
            for ip in observed:
                observed[ip].extend(requests.loc[requests['ip.src'] == ip, 'frame.time_epoch'].tolist())
        for device in devices:
            times = np.array(sorted(observed[device['observed_ipv4']]))
            if len(times) < 2:
                raise ValueError(f'Insufficient requests from device {device["device_id"]} in {name}')
            bins = set(((times-first) // 10).astype(int))
            complete_bins = math.floor((last-first) / 10)
            rows.append({'session': name, 'device_id': device['device_id'], 'model': device['model'],
                'ip': device['observed_ipv4'], 'mac': device['mac'], 'requests': len(times),
                'first_request_epoch': times[0], 'last_request_epoch': times[-1],
                'first_request_after_capture_first_coap_s': times[0] - first,
                'last_request_before_capture_last_coap_s': last - times[-1],
                'maximum_request_gap_s': float(np.diff(times).max()),
                'active_10s_bins': len(bins),
                'capture_10s_bins': math.floor((last-first) / 10) + 1,
                'active_complete_10s_bins': int(sum(index < complete_bins for index in bins)),
                'complete_10s_bins': complete_bins,
                'observed_capture_span_s': last-first})
    if not rows:
        raise ValueError('No client sessions found')
    output.parent.mkdir(parents=True, exist_ok=True)
    with targets[0].open('x', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    report = {'client_sessions': len(rows), 'source_sha256': sources, 'script_sha256': sha(Path(__file__)),
        'max_initial_gap_s': max(r['first_request_after_capture_first_coap_s'] for r in rows),
        'max_final_gap_s': max(r['last_request_before_capture_last_coap_s'] for r in rows),
        'max_request_gap_s': max(r['maximum_request_gap_s'] for r in rows),
        'min_active_10s_bins': min(r['active_10s_bins'] for r in rows),
        'every_client_present_in_every_10s_bin': all(r['active_10s_bins'] == r['capture_10s_bins'] for r in rows),
        'every_client_present_in_every_complete_10s_bin': all(r['active_complete_10s_bins'] == r['complete_10s_bins'] for r in rows),
        'rows': rows, 'csv_sha256': sha(targets[0]),
        'interpretation': 'Request coverage on the server capture clock. Both all bins (including a possibly very short terminal bin) and complete 10 s bins are reported. Audit bins are separate from feature windows and do not establish wireless loss or classifier performance.'}
    with targets[1].open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2); handle.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ['rows', 'source_sha256']}, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--exports', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    audit(args.campaign, args.exports, args.output)
