# A3-23 Interface Compatibility Evidence

Date: 2026-07-26

Scope: provider-side contract verification for the third-layer boundary with
layers 2, 4, and 5. This is not the controller-owned X-03/X-04 full workflow
test and makes no external call.

## Authority checked

- Frozen L1--L5 documents are verified by the S5-00 hash snapshot.
- The orchestration interface manifest remains the public Request/Receipt
  registry; this task does not change its schemas, DTOs, CLI, runtime, or
  database schema.

## Verified boundaries

| Boundary | Evidence | Result |
|---|---|---|
| L2 -> L3 quality input | `QualityGate` accepts only `StableSnapshot`; a non-DTO input becomes a bounded `blocked/snapshot_malformed` result with `repair_data`. | Pass |
| L4 -> L3 revision handoff | `revise_plan` requires the public `plan_id` and `reason_event_id`; an analysis delivery ID is rejected. | Pass |
| L4 delivery ownership | L4 `process` can cite an accepted analysis artifact only as inbound context. Its delivery path requires an L4 response artifact and rejects an injected delivery ID; its DTO has no analysis-delivery field. | Pass |
| L5 -> L3 recovery | `retry_delivery` and `reconcile_delivery` require exactly one `delivery_id` and reject artifact input. The public receipt preserves the exact delivery ID and delivery status. | Pass |
| Shared writes | The exercised seam uses only public DTOs/pure quality input. No test invokes L4/L5 internals or issues database writes; frozen ownership remains L3 `analysis_*`/`training_*`/`analysis_delivery_*`, L4 `mail_*`, and L5 `orchestrator_*`/operational tables. | Pass |

## Limits and handoff

The result establishes L3-side interface compatibility only. The end-to-end
controller workflow, actual scheduling, and any Gmail delivery are intentionally
out of scope and remain owned by X-03/X-04 and later authorized acceptance work.
