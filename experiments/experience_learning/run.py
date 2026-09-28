"""Execute one frozen, disposable, real-service block. Never retry a block."""

import argparse
import asyncio
import json
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

import httpx
import psycopg

from autonomy_lab.environment import provision, teardown
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT, command
from autonomy_lab.procedures import require

from .evaluate import audit_block, decide, inventory, read
from .policy import ARMS, choose, erase, initial, learn
from .protocol import BATCH_SIZE, BLOCK_SECONDS, BLOCKS, DEADLINE_SECONDS, plan, schedule


def feedback_from_responses(records, cases):
    """Online feedback, separately reconstructed by evaluate.classify on replay."""
    feedback = {'offered': BATCH_SIZE, 'timely_correct': 0, 'correct': 0,
                'server_errors': 0, 'dispatch_seconds': []}
    for item in records:
        if item['start'] is None:
            continue
        require(item['status'] is not None, 'Transport uncertainty: no response; stop block')
        case = cases[item['index'] % len(cases)]
        try:
            body = json.loads(item['body'])
            same = ('body' not in case or json.dumps(body, sort_keys=True) ==
                    json.dumps(case['body'], sort_keys=True))
        except ValueError:
            same = 'body' not in case
        ok = item['status'] == case['status_code'] and same
        feedback['correct'] += ok
        feedback['timely_correct'] += ok and item['end'] <= DEADLINE_SECONDS
        feedback['server_errors'] += item['status'] >= 500
        feedback['dispatch_seconds'].append(item['end'] - item['start'])
    return feedback


async def batch_requests(url, cases, concurrency, batch):
    """One simultaneous arrival batch; queued and late work stay in denominator.

    Stop admitting at the SLO, but await every started request. Never cancel late
    requests to manufacture low latency or allow work into the next arm's batch.
    """
    records = [{'index': i, 'case_id': cases[i % len(cases)]['id'], 'start': None,
                'end': None, 'status': None, 'body': None} for i in range(BATCH_SIZE)]
    batch['requests'] = records
    async with httpx.AsyncClient(timeout=6, trust_env=False, follow_redirects=False,
                                 limits=httpx.Limits(max_connections=16, max_keepalive_connections=0)) as client:
        batch['start'] = time.monotonic()
        pending = iter(records)

        async def worker():
            for item in pending:
                start = time.monotonic() - batch['start']
                if start >= DEADLINE_SECONDS:
                    continue
                item['start'] = start
                try:
                    response = await client.get(url + '/quote', params=cases[item['index'] % len(cases)]['params'])
                    item.update(status=response.status_code, body=response.text)
                except httpx.HTTPError as error:
                    # Record class only, without URLs/credentials. No retry.
                    item['transport_error'] = type(error).__name__
                finally:
                    item['end'] = time.monotonic() - batch['start']

        await asyncio.gather(*(worker() for _ in range(concurrency)))
        batch['end'] = time.monotonic()


def control(kube, db, phase, capacity):
    with psycopg.connect(db, autocommit=True, connect_timeout=3,
                        options='-c statement_timeout=1000') as connection:
        if capacity is not None:
            require(capacity in (2, 16), 'Undeclared intervention')
            connection.execute(f'ALTER ROLE inventory_reader CONNECTION LIMIT {capacity}')
        limit = connection.execute("SELECT rolconnlimit FROM pg_roles WHERE rolname = 'inventory_reader'").fetchone()[0]
        rows = connection.execute('SELECT sku, unit_price_minor, stock, currency FROM products ORDER BY sku').fetchall()
    products = [dict(zip(('sku', 'unit_price_minor', 'stock', 'currency'), r, strict=True)) for r in rows]
    pods = json.loads(kube.call('get', 'pods', '-o', 'json'))['items']
    require(len(pods) == 3, 'Unexpected workload population')
    workload = []
    for pod in sorted(pods, key=lambda p: p['metadata']['name']):
        statuses = pod['status']['containerStatuses']
        require(len(statuses) == 1 and statuses[0]['restartCount'] == 0, 'Workload restarted')
        workload.append({'name': pod['metadata']['name'], 'uid': pod['metadata']['uid'],
                         'image_id': statuses[0]['imageID'], 'restarts': statuses[0]['restartCount']})
    service = kube.get_service(kube.namespace, 'inventory')
    require(service['spec']['ports'][0]['targetPort'] == 8080, 'Unexpected routing')
    workload.append({'service_uid': service['metadata']['uid'], 'target_port': 8080})
    return {'phase': phase, 'role_limit': limit, 'products': products, 'workload': workload}


def drain(db, batch):
    # Quote's upstream timeout is 3s. A slow/uncertain response could leave
    # downstream work behind; conservatively withhold the entire block.
    require(all(r['start'] is None or r['end'] - r['start'] < 2.5 for r in batch['requests']),
            'Possible upstream timeout; drain uncertain')
    started = time.monotonic()
    with psycopg.connect(db, autocommit=True, connect_timeout=3,
                        options='-c statement_timeout=1000') as connection:
        while time.monotonic() - started < 5:
            count = connection.execute("SELECT count(*) FROM pg_stat_activity WHERE usename = 'inventory_reader'").fetchone()[0]
            if count == 0:
                waited = time.monotonic() - started
                require(waited < 5, 'Reader connections did not drain in time')
                return {'reader_connections': count, 'wait_seconds': waited}
            time.sleep(.05)
    raise RuntimeError('Reader connections did not drain')


def run_block(declaration_path, block, destination):
    declaration = read(declaration_path)
    declared = declaration['plan']
    require(declared == plan() and 0 <= block < BLOCKS, 'Source or block differs')
    require(declaration['frozen_at'] < time.time(), 'Plan not frozen before execution')
    destination.mkdir(parents=True, exist_ok=False)
    raw = destination / 'raw'
    raw.mkdir()
    save(destination / 'declaration.json', declaration)
    run_id = uuid.uuid4().hex[:8]
    private = ROOT / 'artifacts' / ('learning-environment-' + run_id)
    private.mkdir(parents=True, exist_ok=False)
    ledger = {'status': 'failed', 'block': block, 'run_id': run_id, 'started_at': time.time(),
              'completed_batches': 0, 'planned_batches': len(schedule(block)), 'stage': 'provision'}
    save(destination / 'result.json', ledger)
    deadline = time.monotonic() + BLOCK_SECONDS
    try:
        kube = provision(private, run_id, lease_seconds=3600)
        expectations = read(ROOT / 'fixtures/expectations.json')
        save(raw / 'expectations.json', expectations)
        cases = expectations['quotes']
        last = {arm: None for arm in ARMS}
        controls = []
        with ExitStack() as stack:
            quote_port = stack.enter_context(kube.forward('deployment/quote', 8080))
            db_port = stack.enter_context(kube.forward('deployment/postgres', 5432))
            # Disposable fixture credentials. The policy never receives this DSN.
            db = f'postgresql://postgres:lab-test-only@127.0.0.1:{db_port}/lab'
            for index, identity in enumerate(schedule(block)):
                require(time.monotonic() + 20 < deadline, 'Block wall budget exhausted; retain incomplete original')
                if not controls or identity['phase'] != controls[-1]['phase']:
                    controls.append(control(kube, db, identity['phase'], identity['capacity']))
                    save(raw / 'controls.json', controls)
                    require(controls[-1]['products'] == expectations['products'] and
                            controls[-1]['workload'] == controls[0]['workload'], 'Workload changed')
                arm = identity['arm']
                state = initial() if last[arm] is None else read(last[arm])['after']
                if arm == 'erased' and identity['phase'] == 'retention' and identity['round'] == 0:
                    state = erase(state)
                action = choose(arm, state)
                require(type(action) is int and 1 <= action <= 16, 'Action outside request budget')
                batch = {'identity': identity, 'before': state, 'action': action, 'status': 'started'}
                path = raw / f'batch-{index:03}.json'
                save(path, batch)
                ledger.update(stage='batch', current_batch=index)
                save(destination / 'result.json', ledger)
                try:
                    asyncio.run(batch_requests(f'http://127.0.0.1:{quote_port}', cases, action, batch))
                    feedback = feedback_from_responses(batch['requests'], cases)
                    batch.update(drain=drain(db, batch), feedback=feedback,
                                 after=learn(state, action, feedback), status='complete')
                finally:
                    save(path, batch)
                last[arm] = path
                ledger['completed_batches'] += 1
                save(destination / 'result.json', ledger)
                if (index + 1) % len(ARMS) == 0:
                    print(f'block={block} completed={index + 1}/{len(schedule(block))}', flush=True)
            save(raw / 'final-control.json', control(kube, db, 'final', None))
        require(declared == plan(), 'Source changed during execution')
        ledger['status'] = 'complete'
    except BaseException as error:
        ledger['error_type'] = type(error).__name__
        raise
    finally:
        if (private / 'environment.json').exists():
            try:
                teardown(private)
                require(('autolab-' + run_id) not in command([str(ROOT / '.tools/kind'), 'get', 'clusters']).splitlines(),
                        'Environment still present')
                save(raw / 'cleanup.json', {'status': 'deleted', 'cluster': 'autolab-' + run_id})
            except Exception as error:
                ledger.update(status='failed', cleanup_error_type=type(error).__name__)
                save(raw / 'cleanup.json', {'status': 'failed', 'error_type': type(error).__name__})
        ledger.update(finished_at=time.time(), raw_sha256=inventory(raw))
        save(destination / 'result.json', ledger)
    require(ledger['status'] == 'complete', 'Original block failed')
    rows = audit_block(destination, declared, block)
    save(destination / 'audit.json', {'rows': rows})


def reproduce(declaration_path, source, destination):
    declaration = read(declaration_path)
    require(declaration['plan'] == plan(), 'Source changed')
    require(not destination.exists(), 'Cannot replace reproduction')
    destination.mkdir(parents=True)
    result = {'status': 'incomplete', 'errors': {}, 'decision': None, 'rows': []}
    for block in range(BLOCKS):
        directory = source / f'experience-learning-block-{block}'
        try:
            require(read(directory / 'declaration.json') == declaration, 'Block declaration differs')
            rows = audit_block(directory, declaration['plan'], block)
            require(rows == read(directory / 'audit.json')['rows'], 'Original audit differs')
            result['rows'].extend(rows)
        except Exception as error:
            result['errors'][str(block)] = {'type': type(error).__name__, 'reason': str(error)}
    if not result['errors']:
        from .negative import controls
        try:
            result['negative_controls'] = controls(source / 'experience-learning-block-0', declaration['plan'])
            result.update(status='complete', decision=decide(result['rows']))
        except Exception as error:
            result['errors']['negative_controls'] = {'type': type(error).__name__, 'reason': str(error)}
    save(destination / 'reproduction.json', result)
    require(result['status'] == 'complete', 'Incomplete original study; benefit decision withheld')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    freeze = sub.add_parser('freeze')
    freeze.add_argument('destination', type=Path)
    run = sub.add_parser('run')
    run.add_argument('declaration', type=Path)
    run.add_argument('block', type=int)
    run.add_argument('destination', type=Path)
    replay = sub.add_parser('reproduce')
    replay.add_argument('declaration', type=Path)
    replay.add_argument('source', type=Path)
    replay.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.command == 'freeze':
        require(not args.destination.exists(), 'Cannot replace frozen declaration')
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        save(args.destination, {'frozen_at': time.time(),
                                'commit': command(['git', 'rev-parse', 'HEAD']).strip(), 'plan': plan()})
    elif args.command == 'run':
        run_block(args.declaration, args.block, args.destination)
    else:
        reproduce(args.declaration, args.source, args.destination)
