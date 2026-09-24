# Purpose, evidence and next decisions

Alignment review: 24 September 2026. This is a technical direction check, not a new
experiment result or promotion decision. Historical study outcomes remain unchanged.

## The purpose

The [original question](../PLAN.md) remains the anchor: what evidence should earn
a cloud operator more autonomy? The extended objective is to demonstrate a service
that keeps operating through change and whose operating procedures can improve
under independent evaluation and bounded authority.

The deliverable is a working, reproducible technical and strategic case study:
observable service outcomes, failures that change design decisions, and explicit
decisions about where automation, model reasoning and controlled learning belong.
A null result against capable automation is a useful result. An agent advantage
must be earned by the evidence.

## Alignment of the current evidence

| Question | Evidence available | Decision still unsupported |
|---|---|---|
| Can evaluations determine whether work succeeded and whether a candidate should advance? | Independent semantic/invariant checks, retained unknowns, and a [candidate withheld after a regression miss](RECONCILIATION_RESULTS.md) | General production safety or an automated procedure-promotion system |
| Does more agent structure repay its cost? | [Matched model/runbook comparisons](AGENT_VALUE_RESULTS.md); the apparent observer-outage advantage was closed by a [deterministic fallback](SERVICE_RECOVERY_RESULTS.md) | Structured-state superiority, model necessity or greater repair authority |
| Can state and evidence survive interrupted execution? | Durable operations, conditional repair, response-loss cases and [mixed-state termination gates](MIXED_STATE_RECOVERY_RESULTS.md) | Arbitrary exactly-once effects or host-failure tolerance |
| Can the workload outlive its operator? | [Healthy restart](PERSISTENT_CAMPAIGN_RESULTS.md) and [300-second recurrence](RECURRENCE_RESULTS.md) gates on GCP and CI: unchanged workload, two attributed repairs, then cumulative-budget escalation with the service failure retained; [ambiguous-effect recovery](AMBIGUITY_RESULTS.md) adds no replay after a real unrecorded write, including an external change | Broader sustained incident handling, capacity/release/security autonomy or production availability |
| Can operating experience produce a better operator? | Human-directed interventions and regression evaluations; a [controlled-improvement design](CONTINUOUS_OWNERSHIP_PLAN.md) | An autonomous procedure-generation, promotion and withdrawal loop |
| Does the system reduce customer impact or human work at acceptable cost? | Scoped task outcomes, timings and model usage | Measured human-work savings, full recurring cost advantage or ROI |

The foundation is credible for the bounded claims above. The continuous,
improving-operator objective remains incomplete. Test counts, successful deployment
and source reviews support engineering quality; they are not measures of that
objective's achievement.

## Next proof, in order

1. **Operate through recurring incidents.** Complete the remaining
   [persistent-ownership gates](CONTINUOUS_OWNERSHIP_PLAN.md#evaluation-gates-for-the-implementation)
   using the same workload throughout each campaign. Attributed recurring repair
   and cumulative budget exhaustion pass the bounded recurrence gate; real
   ambiguous-effect reconciliation and external-change refusal also pass on GCP
   and CI. Next prove measurement gaps and supervised campaign-owner cleanup.
   The ambiguity gate does not dispatch a stale proposal to test API rejection.
   Keep the current routing authority. Freeze the fault schedule, deadlines,
   complete calendar, pass criteria and stop conditions before each experiment.
   Escalation can be correct while the service remains failed; retain both facts.

2. **Prove one controlled improvement end to end.** Use an observed incident to
   propose one versioned procedure, retaining its source evidence and dependencies.
   The proposer cannot edit policy, the verifier, hidden cases or promotion rules.
   Exercise regression and sealed lookalike cases, limited rollout, explicit
   promotion authority and withdrawal/rollback. Show that the accepted procedure
   helps on recurrence and avoids applying the fix to a similar symptom with a
   different cause. Rejecting a harmful proposal is required gate evidence;
   demonstrating a beneficial accepted proposal is a separate improvement claim.
   If none qualifies, report that result and do not manufacture a learning success.

3. **Test whether the improvement is worth operating.** Preregister a comparison
   of competent conventional automation, a frozen model-assisted operator and an
   operator allowed only gated procedure updates. Match effective authority,
   starting conditions and schedules, and keep each arm's workload persistent.
   Compare customer correctness/availability measurements, recovery deadlines,
   actual human active time and full operating/learning/evaluation cost. Define
   handling of baseline maintenance, cross-arm feedback and missing measurements.
   Keep fresh cases separate from development feedback. Retain the simpler approach
   when additional model reasoning or learning does not repay its cost.

## Keep effort attached to a decision

Before adding a capability, name the uncertainty it resolves, the observable
outcome, the comparator, and the decision a pass or failure would change. Fix
authority, measurement or recovery defects exposed by these experiments. Freeze
the working foundation between declared experiments so results stay attributable.

Additional agents, broader actions, another cloud, a new runtime integration or a
general platform abstraction need a specific experiment that requires them. Expand
one action family at a time with its own invariants, ownership and rollback gate.
The lab does not claim integration with an internal cloud platform or validate
planet-scale deployment.

The report should lead with decisions and service evidence, keep historical cohorts
separate, and label proposed capabilities. Its current shareable PDF is a dated
research snapshot; these later persistent-service results belong in a clearly dated
update before it is presented as the latest full account. Keep the public report's
technical framing neutral.
