"""Mutate copies of actual evidence, refresh transport hashes, require rejection."""

import json
import shutil
import tempfile

from autonomy_lab.harness import save
from autonomy_lab.procedures import Refused, require

from .evaluate import audit_block, inventory, read


def controls(source, declared):
    results = []
    names = ('wrong_body', 'omitted_request', 'changed_action', 'changed_state',
             'wrong_capacity', 'overlap', 'missing_batch', 'failed_original')
    for name in names:
        with tempfile.TemporaryDirectory(prefix='learning-evidence-control-') as temporary:
            target = source.__class__(temporary) / 'block'
            shutil.copytree(source, target)
            batches = sorted((target / 'raw').glob('batch-*.json'))
            path = batches[0]
            batch = read(path)
            if name == 'wrong_body':
                found = False
                for path in batches:
                    batch = read(path)
                    for request in batch['requests']:
                        if request['status'] == 200 and request['end'] <= 1:
                            body = json.loads(request['body'])
                            body['total_minor'] += 1
                            request['body'] = json.dumps(body)
                            found = True
                            break
                    if found:
                        break
                require(found, 'No actual timely success for semantic corruption control')
            elif name == 'omitted_request':
                batch['requests'].pop()
            elif name == 'changed_action':
                batch['action'] = 999
            elif name == 'changed_state':
                batch['before']['step'] += 1
            elif name == 'wrong_capacity':
                items = read(target / 'raw/controls.json')
                items[0]['role_limit'] = 999
                save(target / 'raw/controls.json', items)
            elif name == 'overlap':
                path = batches[1]
                batch = read(path)
                batch['start'] = read(batches[0])['start']
            elif name == 'missing_batch':
                batches[-1].unlink()
            if name not in ('wrong_capacity', 'missing_batch', 'failed_original'):
                save(path, batch)
            ledger = read(target / 'result.json')
            ledger['raw_sha256'] = inventory(target / 'raw')
            if name == 'failed_original':
                ledger['status'] = 'failed'
            save(target / 'result.json', ledger)
            try:
                audit_block(target, declared, 0)
            except (Refused, FileNotFoundError) as error:
                results.append({'control': name, 'rejected': True, 'reason': str(error)})
            else:
                raise RuntimeError(f'Corrupted original evidence accepted: {name}')
    return results
