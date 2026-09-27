# Bound-dispatch source review

Four bounded Claude Fable 5.1 reviews completed: registry/authority, broker/adapter,
evidence, and focused remediation plus result text. Two oversized token-count
preflights made no generation request. The configured-price estimate for completed
reviews is **$1.36286**, not an invoice. Source hashes, exact excerpt ranges, final
findings and usage are in the [sanitized record](validation/bound-dispatch-review.json).
These are scoped reviews, not independent test executions or merge approval.

## Checked findings

- **Fixed: malformed binding classification.** `execution_conditions` now converts
  structural binding errors to a sanitized `Refused`. Storage failures remain
  unavailable. A test verifies the retained refusal type and reason. The broker
  normally catches malformed stored bindings before calling the authorizer;
  this also makes direct registry validation and the transport guard consistent.
- **Fixed: evidence failure attribution.** The lifecycle result initializes the
  condition check to false and records the stage where evidence failed. An
  authored enclosing-gate test verifies both withholding and the condition stage.
- **Not an exposed path: base-class private promotion.** The proposed trigger
  explicitly calls a base-class private method from trusted Python. Supported
  program promotion is overridden and reproduces raw calibration. The read and
  authorization paths reject a non-program definition. The ledger is not an
  arbitrary-Python sandbox; adding another private-method wrapper would not
  establish one. A qualified later promotion can replace an invalid active
  entry under CAS; withdrawal is not the only possible recovery.
- **Not an exposed path: invalid proposal at authorizer entry.** The trusted broker
  supplies a validated `Proposal`; malformed agent requests cannot reach this
  callback. The campaign catches transport-guard exceptions and records refusals.
  Existing changed-pin, changed-request and pretransport tests pass.
- **Rejected: transport refusal absent from registry.** The follow-up overlooked
  that `campaign.Adapter.patch_service` calls this registry's
  `record_dispatch_refusal` in its exception handler. That is the same durable
  refusal table, not a separate campaign-only record. Guard failures already
  have tests asserting its row count, zero API calls, and the spent claim.
  Recording the refusal again in `authorization` would duplicate it.
- **Retained fail-closed behavior: refusal storage can itself fail.** Such failure
  is intentionally unavailable, not a successful recorded policy refusal. The
  broker sends nothing; the adapter distinguishes known-unsent/refusal-unavailable.
  Preserving a `Refused` type when its durable record cannot be written would
  hide the unavailable-storage condition. Existing tests cover refusal-storage
  failure; the new trigger-abort test also proves authorization and conditions
  roll back together when the second insert fails. No claim is made that an
  unavailable database can persist its own failure receipt.

The follow-up found no overclaim in the final-slot result text and no regression
in the reviewed two-insert transaction. No remaining finding establishes an
execution bypass. Real Kubernetes regression remains a separate required check.

## Local validation before live acceptance

1,814 tests pass; lint and whitespace checks pass. Two dependency deprecation
warnings remain. SIGKILL cases use actual processes and SQLite with an explicitly
authored adapter, not claimed Kubernetes evidence. The original final-slot
archive digest remains unchanged. Precise-contract admission remains disabled.
