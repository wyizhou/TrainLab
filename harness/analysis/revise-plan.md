# Plan-revision route

Use the supplied accepted reason event, original plan and effective date. Create
only a new revision for the remaining dates through the original plan end. Do
not alter items before the effective date, invent a reason, treat free text as
accepted fact or extend the plan into a new seven-day cycle.

Return exactly one `weekly_training_plan` artifact. Its artifact period and
`training_plan.period` are the original full seven-day period, while
`training_plan.items` contains only the consecutive suffix from
`effective_local_date` through the original end date. Number those suffix items
from zero in date order. Copy `original_plan_id`, `original_artifact_id`,
`reason_event_id` and `effective_local_date` exactly from the deterministic
revision contract. Do not return pre-effective items; the host preserves those
stored rows without model involvement.

Use only the supplied 30-completed-day aggregate and activity summaries when
judging the remaining load. Stored FIT, segment, route, set and sensor detail is
outside this route and must not be requested or inferred.

Preserve the fixed Hansons structure when revising running: retain the intended
easy/SOS roles when safe, restore recovery spacing before preserving dose, and
never move a missed SOS session next to another hard run. Every running item
declares its controlled `hansons_session_role`. Re-evaluate both race
goals from current configuration instead of copying stale goal assumptions from
the prior plan.

Limit changes to the accepted constraints and affected dates. Apply the common
safety, source, primary-activity and no-clock-time rules. Cite the exact current
plan artifact and reason event in `source_usage`. Preserve the configured
`training_difficulty_level` in the revised plan constraints unless a
safety- or recovery-driven reduction is required; never increase it merely
because the plan is being revised. Return only route-schema JSON; do not claim
the plan was delivered.
