# Daily route

Produce exactly one `daily_summary` for the completed summary date and one
`daily_training_advice` for the advice date. State coverage, revisions,
available health/sleep/recovery signals, activities, plan adherence, trends,
accepted constraints, uncertainty and source limitations.

Advice may follow, reduce, substitute or rest instead of the current plan, but
must not mutate a formal plan or create a user fact. Missing activity evidence
means unconfirmed, not automatically untrained. Do not treat a partial current
day snapshot as a completed-day trend.

The advice has one primary activity or rest, structured reason and stop
conditions. Running includes source-qualified heart-rate or RPE/talk-test
guidance. Climbing remains recovery/arrangement-only. Strength is movement-only
without sets, repetitions, weight, rest or e1RM. Red flags require rest or
suspension and professional-care guidance.
