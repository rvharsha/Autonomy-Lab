"""Freeze first; one counted Gemini request, no retries or candidate repair."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from autonomy_lab.credentials import gemini_key
from autonomy_lab.gemini import GeminiClient
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT, command
from autonomy_lab.procedures import require
from experiments.experience_learning.evaluate import audit_block as audit_development
from experiments.experience_learning.evaluate import read

from .protocol import SOURCE_LIMIT, plan

SYSTEM = '''Propose exactly one Python 3.12 operating policy from measured development traces.
Return only a JSON object with keys "source" (Python source string) and "rationale"
(short explanation). Do not use markdown fences. No tools or follow-up requests.
Define step(observation) returning exactly {"action": integer 1..16, "memory": object}.
The observation contains step (externally owned spent batch count), memory (your
previous returned object, initially {}), and previous (null initially, otherwise
{"action": last concurrency, "feedback": {"offered":128, "timely_correct":int,
"correct":int, "server_errors":int, "dispatch_seconds":[float,...]}}).
Update memory from previous, then choose the next action. Memory is at most 16384
JSON bytes and source at most 16384 UTF-8 bytes. All state must be returned in memory.
Each decision runs in a fresh Python container, no network, files or credentials,
1 CPU-second and 128 MiB process address space. Standard library only. Deterministic
outputs are mandatory; no random, clock or environment inputs. Write nothing to
stdout. The wrapper serializes your function return. Do not assume a known phase
length, schedule, capacity label, future observation or trial duration. Only your
own measured feedback will be supplied at runtime. Memory may be cleared while
step (spent work) remains unchanged. Do not encode a schedule inferred from step.
Objective: maximize timely semantically correct responses divided by ALL offered
requests, including undispatched and late work. One batch offers 128 simultaneous
arrivals, queuing counts against a one-second SLO. Stop new admissions at one second,
await outstanding work. DB contention produces 503s; 404/422 may be valid responses.
The fixed4 incumbent and unchanged supplied learner are strong comparators. Prefer
simple, fast decisions. Your candidate is frozen without manual repairs before
fresh evaluation. These development data are not held-out evaluation results.
'''


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def freeze(development, destination):
    destination.mkdir(parents=True, exist_ok=False)
    old = read(development / 'experience-learning-plan/declaration.json')
    traces, hashes = [], {}
    for block in range(4):
        directory = development / f'experience-learning-block-{block}'
        audit_development(directory, old['plan'], block)
        for path in sorted((directory / 'raw').glob('batch-*.json')):
            batch = read(path)
            identity, feedback = batch['identity'], batch['feedback']
            durations = sorted(feedback['dispatch_seconds'])
            p90 = durations[min(len(durations) - 1, int(.9 * len(durations)))] if durations else None
            traces.append([block, identity['phase'], identity['round'], identity['arm'], identity['capacity'],
                           batch['action'], feedback['timely_correct'], feedback['server_errors'], len(durations), p90])
            hashes[str(path.relative_to(development))] = hashlib.sha256(path.read_bytes()).hexdigest()
    data = {'development_source': old['commit'], 'raw_sha256': hashes,
            'columns': ['block', 'phase', 'round', 'arm', 'capacity', 'action', 'timely_correct', 'server_errors', 'dispatched', 'p90_dispatch_seconds'],
            'rows': traces}
    # Hash inventories are retained with the packet but not sent as useless tokens.
    prompt_data = {k: v for k, v in data.items() if k != 'raw_sha256'}
    prompt = ('All 1280 development batches (not independent replicas), six cyclic Quote->Inventory->Postgres cases, '
              'four independent workloads with randomized sequential arms. Inventory opens a DB connection per request. '
              'Capacity is a DB connection limit. Each block used four phases of 10 rounds. Fixed4 was strongest pooled '
              'control. Old learner source and full batch-level measured summaries follow.\n' +
              (ROOT / 'experiments/experience_learning/policy.py').read_text() + '\n' +
              json.dumps(prompt_data, separators=(',', ':')))
    request = {'system_instruction': SYSTEM, 'contents': [{'role': 'user', 'parts': [{'text': prompt}]}], 'declarations': []}
    save(destination / 'development.json', data)
    save(destination / 'request.json', request)
    save(destination / 'declaration.json', {'frozen_at': time.time(),
         'source_commit': command(['git', 'rev-parse', 'HEAD']).strip(), 'plan': plan(),
         'request_sha256': digest(request), 'development_sha256': digest(data)})


def verify_proposal(declaration, proposal):
    require(proposal['status'] == 'candidate' and proposal['attempts'] == 1, 'No accepted original proposal')
    require(proposal['declaration_sha256'] == digest(declaration), 'Proposal belongs to another freeze')
    require(proposal['request_sha256'] == declaration['request_sha256'], 'Proposal input differs')
    require(declaration['frozen_at'] < proposal['started_at'] <= proposal['finished_at'], 'Freeze must precede proposal')
    require(proposal['model_version'] == declaration['plan']['model'], 'Wrong provider model')
    require(proposal['counted_input_tokens'] <= declaration['plan']['input_tokens_max'], 'Input budget exceeded')
    require(proposal['usage']['totalTokenCount'] <= proposal['counted_input_tokens'] + declaration['plan']['output_tokens_max'], 'Token reservation exceeded')
    candidate = json.loads(proposal['final_text'])
    require(candidate == proposal['candidate'] and set(candidate) == {'source', 'rationale'}, 'Candidate changed')
    require(type(candidate['source']) is str and 0 < len(candidate['source'].encode()) <= SOURCE_LIMIT, 'Source size invalid')
    require(type(candidate['rationale']) is str, 'Rationale missing')
    require(proposal['source_sha256'] == hashlib.sha256(candidate['source'].encode()).hexdigest(), 'Source bytes changed')


def generate(bundle, private):
    declaration, request = read(bundle / 'declaration.json'), read(bundle / 'request.json')
    require(declaration['plan'] == plan(), 'Frozen source changed')
    require(digest(request) == declaration['request_sha256'] and digest(read(bundle / 'development.json')) == declaration['development_sha256'], 'Frozen input changed')
    private.mkdir(parents=True, exist_ok=False)
    require(not (bundle / 'proposal.json').exists(), 'No proposal replacements')
    record = {'status': 'pending', 'attempts': 0, 'started_at': time.time(),
              'declaration_sha256': digest(declaration), 'request_sha256': digest(request)}
    save(bundle / 'proposal.json', record)  # A durable spent-attempt marker before any provider call.
    try:
        client = GeminiClient(api_key=gemini_key(), model=declaration['plan']['model'], timeout=120)
        record['counted_input_tokens'] = client.count_tokens(**request)
        require(record['counted_input_tokens'] <= declaration['plan']['input_tokens_max'], 'Counted input too large')
        record['attempts'] = 1
        save(bundle / 'proposal.json', record)
        try:
            response = client.generate(**request, max_output_tokens=declaration['plan']['output_tokens_max'])
        except Exception as error:
            if isinstance(getattr(error, 'response', None), dict):
                save(private / 'provider-response.json', error.response)
                record['usage'] = error.response.get('usageMetadata')
                record['model_version'] = error.response.get('modelVersion')
            raise
        save(private / 'provider-response.json', response)
        record.update(usage=response.get('usageMetadata'), model_version=response.get('modelVersion'))
        parts = response['candidates'][0]['content']['parts']
        final = ''.join(p['text'] for p in parts if 'text' in p and not p.get('thought'))
        record['final_text'] = final  # Preserve exact returned text even when invalid JSON.
        record['candidate'] = json.loads(final)
        record['source_sha256'] = hashlib.sha256(record['candidate']['source'].encode()).hexdigest()
        record.update(status='candidate', finished_at=time.time())
        verify_proposal(declaration, record)
        usage = record['usage']
        record['estimated_token_cost_usd'] = (.75 * usage['promptTokenCount'] +
                                            3.75 * (usage['totalTokenCount'] - usage['promptTokenCount'])) / 1e6
        record['pricing_source'] = 'https://ai.google.dev/gemini-api/docs/pricing#gemini-3.8-flash'
        record['cost_is_invoice'] = False
    except BaseException as error:
        record.update(status='rejected_or_incomplete', error_type=type(error).__name__, finished_at=time.time())
        raise
    finally:
        save(bundle / 'proposal.json', record)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['freeze', 'generate'])
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.command == 'freeze':
        freeze(args.source, args.destination)
    else:
        generate(args.source, args.destination)
