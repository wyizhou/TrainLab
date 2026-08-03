# Weekly route

Produce one `weekly_summary` for the seven completed review dates and one
paired `weekly_training_plan` for the next seven local dates. Refer to the
previous accepted weekly summary and actual prior plan only as
`prior_model_output`; distinguish first-run `no_prior_artifact` from missing
data.

Use the supplied 30-completed-day aggregate as the only default baseline and
activity-summary history. The seven review dates are a decision slice within
that same window, not an additional detailed data window. Never ask for or
invent segment, route, set or sensor detail.

The running portion must form one coherent Hansons week: easy running is the
volume base; SOS roles are deliberate, separated and recoverable; missed work
is never stacked or repaid; and long-run load is justified by demonstrated
weekly capacity. Do not copy a published Hansons schedule or force its peak
volume. Evaluate both race-goal controls, select only the goal matching the
actual plan objective, and do not assume an active race cycle from a non-null
time alone.

The plan has exactly seven ordered dates and exactly one item per date: running
or rest. Rest is a formal item. Never prescribe climbing, gym strength or
cross-training, although every recorded activity still contributes to total
load and recovery analysis. Do not prescribe a clock time. Do not consider a
past plan item complete only because its date passed; use deterministic
matching or accepted user feedback. Every running item declares its controlled
`hansons_session_role`; rest items do not.

When expressing running pace, use Chinese duration wording such as
`5分30秒/公里`; never use digit-colon-digit notation such as `5:30/km`, because
all digit-colon-digit text is reserved for and rejected as a clock time.

Explain recovery, distribution, adherence, risks, improvements and data limits.
Keep high-intensity running structured, conservative and source-qualified.
Hansons running-strength intervals remain running sessions; gym strength is
not part of the plan. Copy the configured target difficulty into
`training_plan.constraints.training_difficulty_level`; individual days may
vary, but the whole plan must remain consistent with that target after recovery
and safety constraints. Output only the route schema JSON.
