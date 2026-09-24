"""Deterministic accounting of a frozen campaign calendar, including missing slots."""

import argparse
import hashlib
from collections import Counter
from pathlib import Path

from autonomy_lab.campaign import Contract, operation_rows, read
from autonomy_lab.harness import save


def scorecard(directory):
    contract = Contract.model_validate(read(directory / 'contract.json'))
    window = read(directory / 'window.json')
    if window['end'] - window['start'] != contract.duration_seconds:
        raise ValueError('Measurement window differs from contract')
    rows = []
    requests = Counter()
    latencies = []
    sample_hashes = {}
    for slot in range(contract.duration_seconds // contract.sample_interval_seconds):
        scheduled = window['start'] + slot * contract.sample_interval_seconds
        row = {'slot': slot, 'scheduled_at': scheduled, 'verdict': 'unknown', 'coverage': 'missing'}
        path = directory / 'samples' / f'{slot:04d}.json'
        if path.exists():
            sample_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            sample = read(path)
            if sample['slot'] != slot or sample['scheduled_at'] != scheduled:
                raise ValueError('Sample identity differs from frozen calendar')
            verification = sample.get('verification', {})
            row.update(started_at=sample['started_at'], finished_at=sample['finished_at'],
                       observed_verdict=verification.get('verdict', 'indeterminate'),
                       reasons=verification.get('reasons', [sample.get('error_type', 'missing_verification')]))
            timely = (scheduled <= row['started_at'] <= scheduled + contract.sample_lateness_seconds
                      and row['started_at'] <= row['finished_at'] <= min(window['end'], scheduled + contract.sample_interval_seconds))
            row['coverage'] = 'on_time' if timely else 'late'
            if timely and row['observed_verdict'] in {'verified_success', 'verified_failure'}:
                row['verdict'] = row['observed_verdict']
            for probe in verification.get('probes', []):
                for quote in probe.get('observations', {}).get('quotes', []):
                    requests[quote.get('kind', 'unknown')] += 1
                    if quote.get('kind') == 'response':
                        requests[f"http_{quote.get('status_code', 'unknown')}"] += 1
                        if type(quote.get('status_code')) is not int:
                            row['verdict'] = 'unknown'
                            row['reasons'] = [*row['reasons'], 'malformed_http_observation']
                    if isinstance(quote.get('elapsed_seconds'), (int, float)):
                        latencies.append(quote['elapsed_seconds'])
        rows.append(row)
    expected = {f'{row["slot"]:04d}.json' for row in rows}
    if {p.name for p in (directory / 'samples').glob('*.json')} - expected:
        raise ValueError('Unexpected sample outside frozen calendar')
    workers = []
    for workspace in sorted((directory / 'workers').glob('*')):
        attempts = []
        for episode in sorted(workspace.glob('episode-*')):
            outcome = episode / 'outcome.json'
            attempt = read(episode / 'attempt.json') if (episode / 'attempt.json').exists() else None
            attempts.append({'id': episode.name, 'attempt': attempt,
                             'outcome': read(outcome) if outcome.exists() and attempt is not None else None})
        workers.append({'id': workspace.name, 'attempt': read(workspace / 'attempt.json') if (workspace / 'attempt.json').exists() else None,
                        'ready': read(workspace / 'ready.json') if (workspace / 'ready.json').exists() else None,
                        'failure': read(workspace / 'failed.json') if (workspace / 'failed.json').exists() else None,
                        'episodes': attempts})
    before = read(directory / 'identities-before.json')
    after = read(directory / 'identities-after.json') if (directory / 'identities-after.json').exists() else None
    operations = operation_rows(directory)
    return {
        'claim_scope': 'bounded trusted-runbook lifecycle; sampled observations, not continuous availability',
        'contract': contract.model_dump(), 'window': window, 'source_sha256': read(directory / 'source.json'),
        'owner_finished': (directory / 'finished.json').exists(),
        'owner_failure': read(directory / 'failed.json') if (directory / 'failed.json').exists() else None,
        'owner_finalization': read(directory / 'finalization.json') if (directory / 'finalization.json').exists() else None,
        'cleanup': read(directory / 'cleanup.json') if (directory / 'cleanup.json').exists() else None,
        'identities_before': before, 'identities_after': after,
        'identities_unchanged': None if after is None else before == after,
        'samples': rows, 'sample_sha256': sample_hashes,
        'sample_counts': {key: sum(row['verdict'] == key for row in rows)
                          for key in ['verified_success', 'verified_failure', 'unknown']},
        'measured_requests': dict(sorted(requests.items())),
        'measured_request_latency_seconds': {'count': len(latencies), 'maximum': max(latencies) if latencies else None},
        'workers': workers, 'operations': operations,
        'dispatch_budget_reserved': sum(row['budget_reserved'] for row in operations),
        'limits': ['No inference for intervals between probes.',
                   'Late/missing measurements are unknown even if a later observation succeeds.',
                   'Operator outcomes are claims; only the independent timeline supplies campaign measurements.',
                   'Owner host/cgroup termination and repeated-fault recovery are separate pending gates.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    save(args.output, scorecard(args.directory.resolve()))


if __name__ == '__main__':
    main()
