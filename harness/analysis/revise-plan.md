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

Limit changes to the accepted constraints and affected dates. Apply the common
safety, source, primary-activity and no-clock-time rules. Cite the exact current
plan artifact and reason event in `source_usage`. Return only route-schema JSON;
do not claim the plan was delivered.
