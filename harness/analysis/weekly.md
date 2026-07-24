# Weekly route

Produce one `weekly_summary` for the seven completed review dates and one
paired `weekly_training_plan` for the next seven local dates. Refer to the
previous accepted weekly summary and actual prior plan only as
`prior_model_output`; distinguish first-run `no_prior_artifact` from missing
data.

The plan has exactly seven ordered dates and exactly one primary item per date:
running, climbing, strength or rest. Rest is a formal item. Do not prescribe a
clock time. Do not consider a past plan item complete only because its date
passed; use deterministic matching or accepted user feedback.

Explain recovery, distribution, adherence, risks, improvements and data limits.
Keep high-intensity running structured, conservative and source-qualified.
Climbing contains no grades/routes/dose. Strength is movement-only and avoids
running quality-session conflicts. Output only the route schema JSON.
