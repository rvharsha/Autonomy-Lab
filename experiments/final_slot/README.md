# Final remaining dispatch slot

Prospective six-case confirmation of the exact PR23 combined candidates. Read
`docs/FINAL_SLOT_CONFIRMATION_GATE.md` before interpreting a result. The protocol
and retained-corpus novelty inventory were committed before implementation.

The external harness reuses audited controller, verification and corruption
helpers. It changes the conflict phase and proves one quiet acknowledged first
repair with one slot left. No runtime, authority, budget or candidate changes.
The older contract-confirmation entry point remains retired development only.

The workflow runs on PR opening, not on pushes, so reporting or reviewing a result
cannot automatically repeat this cohort. Freeze and execute once; preserve failures.
Offline reproduction makes no cloud writes or model calls:

    PYTHONPATH=src:scripts:. .venv/bin/python -m experiments.final_slot.run reproduce PLAN DOWNLOAD_DIRECTORY NEW_OUTPUT_DIRECTORY

The download directory contains final-slot-shard-0 through final-slot-shard-2.
Its exact archived source is required. Qualification requires 24 specific negative
controls on copied real evidence; a crash or unrelated rejection never counts.
Selection grants no admission or deployment authority. No live result is claimed
by this source change.
