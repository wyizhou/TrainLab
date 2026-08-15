# Report modes

## Mode comparison

| Contract | `open_report` | `fixed_email` |
| --- | --- | --- |
| Default | Yes | No |
| Renderer | `$data-analytics:build-report` plus `source/templates/open-report/` email shell | `source/templates/fixed/` |
| Layout | Evidence-led and flexible | Stable fixed daily or weekly layout |
| Required source | Validated TrainLab structured output | Same |
| Email result | Static derivative of the persisted canonical report | Fixed `report_artifact` first, then a separate email-safe derivative |
| Sites | Optional, separately authorized | Not used |

## Shared invariants

- Do not alter facts, units, course doses, dates, safety decisions, or provenance.
- Use the exact source output ID and full SHA-256.
- Escape all untrusted text before HTML insertion.
- Keep CSS email-safe and bounded; remove scripts, forms, iframes, remote fonts, tracking pixels,
  event handlers, and active content.
- Preserve a readable plain-text version.
- Record the selected mode and every renderer/template version in lineage.
- A failed render creates a failed run record, not a partial sendable email.
- Treat only validated aggregate values in the bounded source output as report facts. Never load raw
  samples to fill a presentation gap.

## Sites authorization

Sites publication is an external write. Require an approval bound to:

- the canonical report output ID and SHA-256;
- the `sites_publish` action;
- the intended access mode;
- the validity window;
- any scheduled-AI authority chain.

Persist `prepared` before the external call. If the call may have succeeded but the result was not
recorded, mark the action `unknown` and reconcile the Site before retrying.
