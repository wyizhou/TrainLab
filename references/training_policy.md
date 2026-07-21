# Versioned training and safety policy

Version: 2026-07-20

- Long-term goal: effective, stable and gradual improvement of half-marathon
  capability without a fixed race date.
- Heart-rate reserve (%HRR) is the running heart-rate intensity method. Exact BPM
  targets require host-provided maximum and resting heart-rate baselines with
  sufficient evidence. Until those baselines are usable, only a talk-test/RPE
  easy run may be given and no precise heart-rate zone may be invented.
- Use five HRR training zones: Zone 1 is 0% to under 60%, Zone 2 is 60% to
  under 70%, Zone 3 is 70% to under 80%, Zone 4 is 80% to under 90%, and Zone 5
  is 90% through 100%. These are training-management zones, not claimed lactate,
  ventilatory or VO2max thresholds without supporting physiological testing.
  Convert each shared percentage edge to bpm by rounding the new zone's lower
  boundary upward; the preceding zone ends one bpm below it, so zones neither
  overlap nor leave integer gaps.
- Running prescriptions and feedback use a 0-to-10 cardio RPE scale for the
  perceived effort of the whole running segment. Keep it semantically separate
  from any set-level RPE or repetitions-in-reserve convention used for strength.
- Zone guidance pairs HRR with cardio RPE and the talk test. Prescribed Zone 1
  work targets 50-59% HRR at RPE 2-3 with relaxed long sentences; lower values
  remain valid during transitions or walking recovery. Zone 2 is 60-69%, RPE
  3-4 and comfortable full sentences for easy and aerobic endurance running.
  Zone 3 is 70-79%, RPE 5-6 and short sentences for steady or supported
  progression/race-specific work, never the default easy zone. Zone 4 is 80-89%,
  RPE 7-8 and only a few words for controlled hard work. Zone 5 is 90-100%, RPE
  9-10 and isolated words or no speech, and may only be prescribed as brief
  intervals. Zones 4-5 are not labelled as physiological thresholds without
  supporting tests.
- Resting heart rate comes only from Apple Health's daily Resting Heart Rate
  metric. Do not reconstruct it from the lowest sleeping value or arbitrary
  background heart-rate samples. Build its baseline as the median of the most
  recent seven calendar days, require at least five valid days, and recalculate
  it daily. Activate the initial baseline immediately once that five-of-seven
  requirement is met; the 14-day rule applies only to a significant upward change
  from an established baseline. Use only completed local calendar days; the current day's value is a
  provisional recovery signal and never enters the prescription baseline. If
  fewer than five days are valid, disable precise HRR targets rather than guessing.
  An increase of at least 5% over the current baseline, with an absolute minimum
  threshold of 3 bpm, is a recovery-risk signal and defers any upward baseline
  update pending further evidence. The first completed day is a provisional
  warning; two consecutive completed days confirm a sustained recovery-risk
  signal. This signal alone neither diagnoses illness nor changes training. A
  higher value becomes an upward baseline candidate only after the significant
  increase persists for 14 consecutive completed local days; retain the existing
  lower prescription baseline until then. Judge candidate stability using only
  the final seven completed days of that candidate period. Their maximum-minus-
  minimum range must be no more than 3 bpm; otherwise retain the existing baseline
  and continue the rolling observation without clearing history. Once stable,
  select the median of those seven candidate values as the supported new baseline.
  Do not adopt it while an acute illness, active injury, red-flag symptom or an
  explicit user report of not being recovered remains active. Preserve the
  candidate history and recheck after the blocker clears. Objective recovery
  metrics may corroborate the decision but cannot permanently block adoption by
  themselves.
- Adopt a lower seven-day resting-heart-rate median immediately because it makes
  the prescription more conservative. A decrease of at least 5%, with a minimum
  threshold of 3 bpm, also triggers a recovery, sleep and user-feedback check;
  never infer improved fitness from that signal alone.
- If the profile lists medication that materially affects heart-rate response,
  disable precise HRR targets pending qualified guidance and use RPE plus the
  talk test instead. An empty list means no such medication is currently reported.
- Maximum heart rate uses credible sustained peaks from Apple Health workout
  samples first. A workout candidate is based on the highest rolling median over
  a 10-second heart-rate window, never a single peak sample. The window requires
  at least eight valid samples, may not contain an internal gap longer than two
  seconds, and is discarded rather than imputed when incomplete beyond those
  limits. Heart rate being close to running cadence is a motion-artifact risk
  signal, not a rejection by itself. Treat it as close when the difference is no
  more than 2% of cadence, with a minimum tolerance of 3 bpm. Tracking must persist for at least 30 seconds
  before it counts as sustained. Reject suspected cadence lock only with joint
  evidence of abrupt convergence, sustained cadence tracking and a response
  inconsistent with pace or power. Every imported run
  is evaluated, but ordinary-run peaks are observations only. A peak becomes a
  candidate only when pace, power, heart-rate rise, segment duration and workout
  context jointly identify a near-maximal running segment lasting at least three
  continuous minutes. The heart-rate shape is mandatory and must be corroborated
  by at least one of individualized pace/power or workout structure; no percentage
  of an age formula is used as a candidate gate. A continuous plausible rise or a
  high stable response is an acceptable heart-rate shape. A heart-rate plateau is
  a confidence booster, not a mandatory gate. The candidate peak may occur anywhere
  in the three-minute segment; occurrence in the final 60 seconds adds confidence
  but is not required. A baseline change requires mutually
  supporting candidates from at least two different local dates. Supporting
  candidates may differ by no more than 5 bpm, and the lower candidate becomes
  the conservative supported value. A lower observation cannot reduce an
  established baseline because an ordinary run is not evidence of a lower
  physiological maximum. The Tanaka `208 - 0.7 x age` formula is only a
  low-confidence fallback. It may only support approximate Zone 1-2 targets with
  mandatory RPE and talk-test guidance; it may not authorize Zone 3-5 targets or
  quality sessions by itself. A supported historical maximum makes Zone 3-4
  eligible when the wider recovery and load context permits, but Zone 5 remains
  locked until two successful Zone 4 sessions on distinct local dates, separated
  by at least 72 hours, demonstrate prior adaptation. Zone 5 is never a continuous
  prescription. A successful session must have no warning symptom or acute injury
  reported through TrainLab feedback. With no email reply, this gate passes as
  "no warning symptom reported", not as medical confirmation that the user was
  symptom-free. A later explicit report invalidates the affected session. At
  least 80% of the planned Zone 4 work duration must be completed; warm-up,
  recovery and cool-down do not count. Falling below 80% means insufficient
  unlock evidence, not a failed workout. Within completed Zone 4 work, at least
  50% of valid heart-rate time must fall in Zone 4. Calculate this by elapsed
  time, not sample count; Zone 5 time does not count toward the 50% minimum and
  may occupy at most 10% of completed Zone 4 work. More than 10% means the
  session was not controlled Zone 4 unlock evidence, not that the workout failed.
  Valid heart-rate data must cover at least 80% of completed Zone 4 work, with no
  imputation. Lower coverage makes the result indeterminate rather than a success
  or failure. Classify zones from a 10-second rolling median. Each window needs at
  least eight samples and no sample gap over two seconds. More than ten continuous
  seconds without a valid window inside a Zone 4 work interval invalidates only
  that interval, which then counts as uncompleted; gaps during pauses, recoveries
  and cool-down do not apply. RPE feedback is optional secondary evidence. No RPE
  report carries no penalty; RPE 7-8 supports controlled Zone 4, RPE 9-10 makes
  it uncontrolled evidence, and RPE 0-6 makes it indeterminate pending heart-rate
  baseline review. Equivalent explicit wording may be used when no number is given.
- Strength is a movement-only, full-body recommendation supporting running and
  climbing. It does not depend on exercise history, e1RM, equipment increments,
  sets, repetitions or kilograms. It returns catalog exercises and host-resolved
  YouTube links only.
- Device anomalies alone do not change training. Explicit symptoms such as chest
  discomfort, fainting, severe dizziness, unusual shortness of breath, or acute
  injury suspend the prescription.
- Stop conditions appear on every running and strength prescription.
- The canonical, Schema-validated Zone parameters live in
  `config/running_policy.yaml`; the complete Chinese rationale and operational
  thresholds are documented in `references/heart_rate_zone_policy.zh-CN.md`.
- Zone 5 is host-gated, never all-out or continuous, limited to one session per
  rolling seven days, and begins with four 60-second repetitions separated by
  120 seconds of Zone 1/low Zone 2 recovery. All Zone 4/5 quality sessions are
  at least 72 hours apart.
- Zone 5 authorization expires after 21 days without Zone 4/5 evidence and can
  be restored by one successful Zone 4 session. At 42 days it fully resets to
  the original two-session unlock. A supported baseline revision of at least
  five bpm also requires one successful Zone 4 revalidation.
- The canonical cross-sport decision, recovery, climbing, feedback and strength
  defaults live in `config/decision_policy.yaml` and
  `config/strength_policy.yaml`. The user selects the start clock time. Running
  begins with a 30-minute easy main set when history is insufficient; progression
  is not forced and changes only one load dimension at a time.
- A climbing recommendation is only `今日攀岩` plus one recovery-based sentence;
  duration, route, grade and drills are prohibited.
- Strength is enabled in movement-only mode and requires no historical load data.
  It covers squat/single-leg, hinge, pull, push and anti-rotation patterns while
  omitting sets, repetitions, rest, percentages and kilograms.
- The concise Chinese policy guide and the distinction between external evidence
  and TrainLab engineering thresholds are in
  `references/default_strategy_summary.zh-CN.md`.

Sources:
- WHO physical activity guidelines: https://www.who.int/publications/i/item/9789240014886
- AHA activity warning signs: https://www.heart.org/en/health-topics/cardiac-rehab/getting-physically-active/develop-a-physical-activity-plan-for-you
