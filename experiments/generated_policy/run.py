"""One real-service attempt; preserve failed and incomplete originals."""

import argparse
import asyncio
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

from autonomy_lab.environment import provision, reset_application, teardown
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT, command
from autonomy_lab.procedures import require
from experiments.experience_learning.evaluate import inventory, read
from experiments.experience_learning.run import (
    batch_requests,
    control,
    drain,
    feedback_from_responses,
)

from .evaluate import audit_block, decide, observation
from .propose import verify_proposal
from .protocol import BLOCK_SECONDS, BLOCKS, plan, schedule
from .runtime import image, invoke, source_for


def run_block(bundle, block, destination):
    declaration = read(bundle / 'declaration.json')
    proposal = read(bundle / 'proposal.json')
    require(declaration['plan'] == plan(), 'Frozen source differs')
    verify_proposal(declaration, proposal)
    require(0 <= block < BLOCKS, 'Invalid block')
    destination.mkdir(parents=True, exist_ok=False)
    raw = destination / 'raw'
    raw.mkdir()
    save(destination / 'declaration.json', declaration)
    save(raw / 'proposal.json', proposal)
    run_id = uuid.uuid4().hex[:8]
    private = ROOT / 'artifacts' / ('generated-environment-' + run_id)
    private.mkdir(parents=True, exist_ok=False)
    ledger = {'status': 'failed', 'block': block, 'run_id': run_id, 'started_at': time.time(),
              'completed_batches': 0, 'planned_batches': len(schedule(block)), 'stage': 'image'}
    save(destination / 'result.json', ledger)
    deadline = time.monotonic() + BLOCK_SECONDS
    try:
        image_id = image()
        ledger.update(policy_image=image_id, stage='provision')
        save(destination / 'result.json', ledger)
        kube = provision(private, run_id, lease_seconds=3600)
        environment = read(private / 'environment.json')
        expectations = read(ROOT / 'fixtures/expectations.json')
        save(raw / 'expectations.json', expectations)
        controls, index = [], 0
        arms = list(dict.fromkeys(r['arm'] for r in schedule(block)))
        for arm_index, arm in enumerate(arms):
            if arm_index:
                reset_application(kube, environment['app_image'], environment['toolchain']['postgres_image'])
            last, phase = None, None
            with ExitStack() as stack:
                quote_port = stack.enter_context(kube.forward('deployment/quote', 8080))
                db_port = stack.enter_context(kube.forward('deployment/postgres', 5432))
                db = f'postgresql://postgres:lab-test-only@127.0.0.1:{db_port}/lab'
                for identity in (r for r in schedule(block) if r['arm'] == arm):
                    require(time.monotonic() + 30 < deadline, 'Block wall budget exhausted')
                    if phase != identity['phase']:
                        phase = identity['phase']
                        controls.append({'arm': arm, **control(kube, db, phase, identity['capacity'])})
                        save(raw / 'controls.json', controls)
                    before = observation(last, identity)
                    batch = {'identity': identity, 'before': before, 'status': 'started', 'policy_start': time.monotonic()}
                    path = raw / f'batch-{index:03}.json'
                    save(path, batch)
                    ledger.update(stage='batch', current_batch=index)
                    save(destination / 'result.json', ledger)
                    try:
                        batch['decision'] = invoke(source_for(arm, proposal['candidate']['source']), before, image_id)
                        batch['policy_end'] = time.monotonic()
                        batch['action'] = batch['decision']['result']['action']
                        asyncio.run(batch_requests(f'http://127.0.0.1:{quote_port}', expectations['quotes'], batch['action'], batch))
                        batch.update(feedback=feedback_from_responses(batch['requests'], expectations['quotes']),
                                     drain=drain(db, batch), status='complete')
                    except BaseException as error:
                        batch['error'] = {'type': type(error).__name__,
                                          'policy_error_type': getattr(error, 'policy_error_type', None),
                                          'cleanup_error_type': getattr(error, 'cleanup_error_type', None)}
                        raise
                    finally:
                        save(path, batch)
                    last = read(path)  # Cross every boundary through durable JSON.
                    index += 1
                    ledger['completed_batches'] = index
                    save(destination / 'result.json', ledger)
                controls.append({'arm': arm, **control(kube, db, 'final', None)})
                save(raw / 'controls.json', controls)
            print(f'block={block} completed={arm} batches={index}', flush=True)
        require(declaration['plan'] == plan(), 'Source changed during execution')
        ledger['status'] = 'complete'
    except BaseException as error:
        ledger['error_type'] = type(error).__name__
        raise
    finally:
        if (private / 'environment.json').exists():
            try:
                teardown(private)
                require(('autolab-' + run_id) not in command([str(ROOT / '.tools/kind'), 'get', 'clusters']).splitlines(), 'Cluster still present')
                save(raw / 'cleanup.json', {'status': 'deleted', 'cluster': 'autolab-' + run_id})
            except Exception as error:
                ledger.update(status='failed', cleanup_error_type=type(error).__name__)
                save(raw / 'cleanup.json', {'status': 'failed', 'error_type': type(error).__name__})
        ledger.update(finished_at=time.time(), raw_sha256=inventory(raw))
        save(destination / 'result.json', ledger)
    require(ledger['status'] == 'complete', 'Original block failed')


def reproduce(bundle, source, destination):
    declaration = read(bundle / 'declaration.json')
    require(declaration['plan'] == plan(), 'Frozen source differs')
    destination.mkdir(parents=True, exist_ok=False)
    result = {'status': 'incomplete', 'errors': {}, 'rows': [], 'decision': None}
    save(destination / 'reproduction.json', result)
    image_id = image()
    for block in range(BLOCKS):
        try:
            result['rows'].extend(audit_block(source / f'generated-policy-block-{block}', declaration, block, image_id))
        except Exception as error:
            result['errors'][str(block)] = {'type': type(error).__name__, 'reason': str(error)}
        save(destination / 'reproduction.json', result)
    if not result['errors']:
        from .negative import controls
        try:
            result['negative_controls'] = []
            def progress(items):
                result['negative_controls'] = items
                save(destination / 'reproduction.json', result)
            controls(source / 'generated-policy-block-0', declaration, image_id, progress)
            result.update(status='complete', decision=decide(result['rows']))
        except Exception as error:
            result['errors']['negative_controls'] = {'type': type(error).__name__, 'reason': str(error)}
    save(destination / 'reproduction.json', result)
    require(result['status'] == 'complete', 'Incomplete original study; decisions withheld')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('bundle', type=Path)
    run.add_argument('block', type=int)
    run.add_argument('destination', type=Path)
    replay = sub.add_parser('reproduce')
    replay.add_argument('bundle', type=Path)
    replay.add_argument('source', type=Path)
    replay.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.command == 'run':
        run_block(args.bundle, args.block, args.destination)
    else:
        reproduce(args.bundle, args.source, args.destination)
