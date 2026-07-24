# Plan-revision route

Use the supplied accepted reason event, original plan and effective date. Create
only a new revision for the remaining dates through the original plan end. Do
not alter items before the effective date, invent a reason, treat free text as
accepted fact or extend the plan into a new seven-day cycle.

Preserve `supersedes`, `derived_from` and `references_prior_plan` lineage in
the structured result. Limit changes to the affected constraints and dates.
Apply the common safety, source, primary-activity and no-clock-time rules.
Return only route-schema JSON; do not claim the plan was delivered.
