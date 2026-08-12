# A3-22 synthetic end-to-end and safety coverage report

Date: 2026-07-26
Scope: offline, synthetic validation only. No Codex process, Gmail MCP client,
network request, production database, or production health record is used.

## Preconditions

The five frozen contract SHA-256 values match the A3-22 plan snapshot:

| Contract | Result |
|---|---|
| Foundation v2.4 | match |
| Collection v1 | match |
| Analysis v2.1 | match |
| Mail Agent v2.1 | match |
| Orchestration v1.1 | match |

## Automated coverage matrix

| Required path / boundary | Synthetic evidence |
|---|---|
| Daily: accepted, quality-blocked, unchanged, lock-busy, rejected runner/validator | `tests/test_analysis_a3_17.py` |
| Weekly: rolling window, accepted plan/delivery, blocked and delivery-pending failure | `tests/test_analysis_a3_18.py`, `tests/test_analysis_a3_18_publisher.py`, `tests/test_analysis_a3_18_validation.py` |
| Revise plan: trusted reason, suffix-only revision, blocked/rejected paths | `tests/test_analysis_a3_19.py`, `tests/test_analysis_a3_19_publisher.py`, `tests/test_analysis_a3_19_reason.py`, `tests/test_analysis_a3_19_validation.py` |
| Regenerate: frozen reason catalog, target resolution, immutable new revision, rollback | `tests/test_analysis_a3_20.py` |
| Status: select-only, subject isolation and body/provider redaction | `tests/test_analysis_a3_21.py`, `tests/test_analysis_a3_22_e2e.py` |
| Retry/reconcile: timeout to `delivery_unknown`, retry suppression, reconcile match/no-match, terminal no-op | `tests/test_analysis_delivery_service.py`, `tests/test_analysis_a3_16.py`, `tests/test_analysis_a3_22_e2e.py` |
| Atomicity/crash faults | `tests/test_analysis_a3_13.py`, `tests/test_analysis_a3_22_e2e.py` |
| Gmail/Codex isolation | injected fake runner/gateway in all route tests; no production runtime composition root is invoked |
| Privacy | status tests assert report bodies, provider IDs/threads, error detail and structured content are absent |
| Background cleanup | `tests/test_analysis_a3_22_e2e.py` compares live threads before/after unknown/reconcile flow; routes use one-shot injected collaborators |

## Result interpretation

The suite is evidence for third-layer synthetic behavior, not a production
acceptance result. It intentionally does not cover A3-23 cross-layer
integration, A3-24 shadow migration, or A3-25 controlled real-environment
acceptance. Those require their separately authorized gates.

## Verification performed

On 2026-07-26, the focused matrix above completed successfully with the
project virtual environment. The A3-22 additions also passed bytecode
compilation and `git diff --check`. No real-provider tool or production command
was invoked.
