"""Mutate copies of actual evidence, refresh transport hashes, require rejection."""

import json
import shutil
import tempfile

from autonomy_lab.harness import save
from autonomy_lab.procedures import Refused, require

from .evaluate import audit_block, classify, inventory, read, strict_equal


def controls(source, declared, image_id, progress=lambda items: None):
    block = read(source / 'result.json')['block']
    # A reject-everything auditor or wrong environment cannot pass these controls.
    audit_block(source, declared, block, image_id)
    reasons = {'wrong_body': 'Feedback differs', 'omitted_request': 'Offered population missing',
               'changed_action': 'Action differs', 'changed_state': 'Observation does not replay',
               'wrong_context': 'Observation does not replay',
               'learned_state': 'Nondeterministic or altered policy result',
               'wrong_capacity': 'Control identity or capacity differs',
               'overlap': 'Overlapping or invalid decision/batch timing',
               'failed_original': 'Original block incomplete'}
    results = []
    names = ('wrong_body', 'omitted_request', 'changed_action', 'changed_state',
             'wrong_context', 'learned_state', 'wrong_capacity', 'overlap', 'missing_batch', 'failed_original')
    for name in names:
        with tempfile.TemporaryDirectory(prefix='learning-evidence-control-') as temporary:
            target = source.__class__(temporary) / 'block'
            shutil.copytree(source, target)
            batches = sorted((target / 'raw').glob('batch-*.json'))
            path = batches[0]
            batch = read(path)
            if name == 'wrong_body':
                found = False
                cases = read(target / 'raw/expectations.json')['quotes']
                for path in batches:
                    batch = read(path)
                    for request in batch['requests']:
                        if request['status'] == 200 and request['end'] <= 1:
                            body = json.loads(request['body'])
                            case = cases[request['index'] % len(cases)]
                            if not strict_equal(body, case.get('body')):
                                continue
                            before = classify(batch['requests'], cases, batch['action'])
                            body['total_minor'] += 1
                            request['body'] = json.dumps(body)
                            after = classify(batch['requests'], cases, batch['action'])
                            require(after['timely_correct'] == before['timely_correct'] - 1, 'Semantic control did not change reward')
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
            elif name == 'wrong_context':
                batch['before']['context'] = 'unobserved-mode'
            elif name == 'learned_state':
                batch['decision']['result']['memory'] = {'forged_reward_estimates': True}
            elif name == 'wrong_capacity':
                items = read(target / 'raw/controls.json')
                items[0]['role_limit'] = 999
                save(target / 'raw/controls.json', items)
            elif name == 'overlap':
                path = batches[1]
                batch = read(path)
                batch['start'] = read(batches[0])['start']
            elif name == 'missing_batch':
                batches[0].unlink()
            if name not in ('wrong_capacity', 'missing_batch', 'failed_original'):
                save(path, batch)
            ledger = read(target / 'result.json')
            ledger['raw_sha256'] = inventory(target / 'raw')
            if name == 'failed_original':
                ledger['status'] = 'failed'
            save(target / 'result.json', ledger)
            try:
                audit_block(target, declared, block, image_id)
            except (Refused, FileNotFoundError) as error:
                if name == 'missing_batch':
                    require(isinstance(error, FileNotFoundError) and
                            error.filename == str(target / 'raw/batch-000.json'), 'Wrong missing-file rejection')
                else:
                    require(isinstance(error, Refused) and str(error) == reasons[name],
                            f'Control {name} rejected for an unrelated reason')
                results.append({'control': name, 'rejected': True, 'reason': str(error),
                                'unmodified_original_accepted': True})
                progress(results)
            else:
                raise RuntimeError(f'Corrupted original evidence accepted: {name}')
    return results
