"""A3-08 bounded deterministic features; no I/O, clock, model, or provider calls."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from hashlib import sha256
import json, math, re
from statistics import median
from typing import Any, Iterable, Mapping
from .stable_views import StableSnapshot

FEATURE_LIBRARY_VERSION = "2"
CONFLICT_POLICY_VERSION = "2"
CONFLICT_POLICY_SHA256 = "271c03e24bd57b6060e3ee524d492a574ab003e529994e054187315e5fd81f35"
VALUE_ORIGIN = "derived_statistic"
ALLOWED_WINDOWS = frozenset((7, 14, 28)); _MAX_ROWS = 4000; _MAX_MATCH = 16
_ORIGINS = frozenset(("provider_fact","provider_derived","provider_predicted","user_asserted","derived_statistic","prior_model_output","unknown"))
_KINDS = frozenset(("running","climbing","strength","rest"))
_PROHIBITED_OPERATIONS = frozenset(("simulate_provider_algorithm","reconstruct_provider_algorithm","derive_provider_algorithm","derive_hr_boundaries_from_time_in_zone","derive_max_hr_from_single_sample"))
class FeatureError(ValueError): pass
@dataclass(frozen=True)
class DeterministicFeature:
 key:str; value:float|int|None; metric:str; unit:str|None; window_start_local_date:str; window_end_local_date:str; sample_count:int; expected_count:int; missing_count:int; input_revision_ids:tuple[str,...]; value_origin:str=VALUE_ORIGIN; algorithm_version:str=FEATURE_LIBRARY_VERSION
 def as_dict(self)->dict[str,Any]: return asdict(self)
def _fail(x:str)->None: raise FeatureError(x)
def _num(x:Any)->float:
 if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(float(x)): _fail("feature_number_invalid")
 return float(x)
def _date(x:Any)->date:
 if not isinstance(x,str): _fail("feature_date_invalid")
 try:return date.fromisoformat(x)
 except ValueError as e: raise FeatureError("feature_date_invalid") from e
def _utc(x:Any)->datetime:
 if not isinstance(x,str) or not x.endswith("Z"): _fail("feature_utc_invalid")
 try:return datetime.fromisoformat(x[:-1]+"+00:00")
 except ValueError as e: raise FeatureError("feature_utc_invalid") from e
def _rows(items:Iterable[Mapping[str,Any]])->tuple[Mapping[str,Any],...]:
 out=[]
 try:
  iterator=iter(items)
  for _ in range(_MAX_ROWS+1):
   try: row=next(iterator)
   except StopIteration: break
   if not isinstance(row,Mapping): _fail("feature_shape_invalid")
   out.append(row)
 except FeatureError: raise
 except Exception as e: raise FeatureError("feature_iterable_invalid") from e
 if len(out)>_MAX_ROWS:_fail("feature_input_unbounded")
 subjects={r.get("subject_id") for r in out if r.get("subject_id") is not None}
 if len(subjects)>1 or any(isinstance(x,bool) or not isinstance(x,(int,str)) for x in subjects):_fail("feature_cross_subject")
 return tuple(out)
def _same_subject(*groups:Iterable[Mapping[str,Any]])->None:
 subjects={r.get("subject_id") for group in groups for r in group if r.get("subject_id") is not None}
 if len(subjects)>1:_fail("feature_cross_subject")
def _id(row:Mapping[str,Any], key="id")->str:
 x=row.get(key)
 if x is None or isinstance(x,bool) or not isinstance(x,(str,int)): _fail("feature_identity_invalid")
 return str(x)
def _rev(row:Mapping[str,Any])->str:
 x=row.get("source_revision_id",row.get("primary_revision_id"))
 if x is None or isinstance(x,bool) or not isinstance(x,(str,int)): _fail("feature_revision_invalid")
 return str(x)
def _coverage_rev(row:Mapping[str,Any])->str:
 if row.get("source_revision_current") is not None and row.get("source_revision_current") != 1:_fail("feature_noncurrent_coverage")
 if row.get("source_revision_id") is not None:return _rev(row)
 return "coverage:"+_id(row)
def _activity_revisions(row:Mapping[str,Any])->tuple[str,...]:
 extra=row.get("structure_revision_ids",())
 if not isinstance(extra,(list,tuple)) or any(isinstance(x,bool) or not isinstance(x,(str,int)) for x in extra):_fail("feature_revision_invalid")
 return tuple(sorted({_rev(row),*(str(x) for x in extra)}))
def _json(x:Any)->str:
 try:return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
 except (TypeError,ValueError) as e: raise FeatureError("feature_serialization_invalid") from e
def stable_hash(value:Any)->str:return sha256(_json(value).encode()).hexdigest()
def _norm(metric:str)->str:
 if not isinstance(metric,str) or not metric:_fail("feature_metric_invalid")
 return re.sub(r"[^a-z0-9]","",metric.lower().replace("₂","2"))
def reject_prohibited_metric(metric:str)->None:
 """Compatibility helper: names are evidence, not algorithms, and are legal."""
 _norm(metric)
def _operation(kind:str)->None:
 if kind in _PROHIBITED_OPERATIONS:_fail("feature_prohibited_operation")
 if kind not in {"aggregate","sum","distribution","match","interval","impact","evidence"}:_fail("feature_operation_invalid")
def _kind(x:Any)->str:return {"run":"running","bouldering":"climbing","rockclimbing":"climbing","gym":"strength"}.get(_norm(str(x)),_norm(str(x)))
def _meta(rows:Iterable[Mapping[str,Any]],start:date,end:date)->dict[str,Any]:
 r=_rows(rows); return {"window_start_local_date":start.isoformat(),"window_end_local_date":end.isoformat(),"input_revision_ids":tuple(sorted({_rev(x) for x in r}))}

def window_statistics(rows:Iterable[Mapping[str,Any]],*,metric:str,unit:str,end_local_date:str,window_days:int,date_key="local_date",value_key="value_number",operation_kind="aggregate",evidence_verified=False,coverage_rows:Iterable[Mapping[str,Any]]|None=None)->tuple[DeterministicFeature,...]:
 _operation(operation_kind); reject_prohibited_metric(metric)
 if window_days not in ALLOWED_WINDOWS or not isinstance(unit,str) or not unit:_fail("feature_window_or_unit_invalid")
 end=_date(end_local_date);start=end-timedelta(days=window_days-1);need={start+timedelta(days=i) for i in range(window_days)};known={};coverage_revisions=()
 input_rows=_rows(rows); provider_rows=[r for r in input_rows if str(r.get("value_origin","")).startswith("provider_")]
 coverage=_rows(coverage_rows or ())
 if provider_rows:
  if evidence_verified is not True or not coverage:_fail("feature_provider_evidence_unverified")
  if len(provider_rows)!=len(input_rows):_fail("feature_provider_scope_mixed")
  provider_keys=set()
  for r in provider_rows:
   sid=r.get("subject_id");resource=r.get("resource_kind")
   if sid is None or isinstance(sid,bool) or not isinstance(sid,(str,int)):_fail("feature_provider_identity_invalid")
   if r.get("provider")!="garmin" or not isinstance(resource,str) or not resource:_fail("feature_provider_identity_invalid")
   if r.get("current_revision") is not True:_fail("feature_noncurrent_input")
   _rev(r);provider_keys.add((sid,"garmin",resource))
  if len(provider_keys)!=1:_fail("feature_provider_scope_mixed")
  provider_key=next(iter(provider_keys));coverage_by_date={}
  for c in coverage:
   if (c.get("subject_id"),c.get("provider"),c.get("resource_kind"))!=provider_key:_fail("feature_provider_coverage_scope_invalid")
   d=_date(c.get("local_date"))
   if d not in need:_fail("feature_coverage_out_of_window")
   if d in coverage_by_date:_fail("feature_duplicate_coverage")
   current_marker=c.get("source_revision_current")
   if isinstance(current_marker,bool) or current_marker!=1 or (c.get("current_revision") is not None and c.get("current_revision") is not True):_fail("feature_noncurrent_coverage")
   if c.get("availability_state") not in {"fetched","empty"}:_fail("feature_provider_coverage_invalid")
   _id(c);coverage_by_date[d]=c
  if set(coverage_by_date)!=need:_fail("feature_coverage_incomplete")
  for r in provider_rows:
   d=_date(r.get(date_key))
   if d not in need:_fail("feature_provider_row_out_of_window")
   c=coverage_by_date[d]
   if c.get("availability_state")!="fetched" or c.get("source_revision_id") is None or str(c.get("source_revision_id"))!=_rev(r):_fail("feature_provider_coverage_invalid")
  coverage_revisions=tuple(sorted({_coverage_rev(c) for c in coverage_by_date.values()}))
 for r in input_rows:
  d=_date(r.get(date_key));
  if d>end:_fail("feature_future_date")
  if d<start:continue
  if d in known:_fail("feature_duplicate_identity")
  if r.get("canonical_unit",r.get("unit",unit))!=unit:_fail("feature_unit_incompatible")
  if r.get("value_origin") is not None and r.get("value_origin") not in {"provider_fact","provider_derived","provider_predicted","user_asserted","derived_statistic"}:_fail("feature_origin_invalid")
  if r.get("current_revision") is False:_fail("feature_noncurrent_input")
  known[d]=(_num(r.get(value_key)),_rev(r))
 vals=[known[x][0] for x in sorted(known)]; rev=tuple(sorted({*(x[1] for x in known.values()),*coverage_revisions})); n=len(vals); common=dict(window_start_local_date=start.isoformat(),window_end_local_date=end.isoformat(),sample_count=n,expected_count=window_days,missing_count=window_days-n,input_revision_ids=rev)
 pairs=(("count",n,"count"),("sum",sum(vals) if vals else None,unit),("mean",sum(vals)/n if n else None,unit),("median",median(vals) if vals else None,unit),("change",vals[-1]-vals[0] if n>1 else None,unit),("missing_rate",(window_days-n)/window_days,"ratio"))
 return tuple(DeterministicFeature(f"{metric}.{name}.{window_days}d",v,metric,u,**common) for name,v,u in pairs)

def activity_distribution(activities:Iterable[Mapping[str,Any]],*,end_local_date:str,window_days:int,coverage_complete_dates:Iterable[Any],rest_plan_items:Iterable[Mapping[str,Any]]=())->tuple[DeterministicFeature,...]:
 if window_days not in ALLOWED_WINDOWS:_fail("feature_window_invalid")
 end=_date(end_local_date);start=end-timedelta(days=window_days-1); need={start+timedelta(days=i) for i in range(window_days)}
 raw_coverage=_rows(coverage_complete_dates)
 activity_rows=_rows(activities);rest_rows=_rows(rest_plan_items);_same_subject(raw_coverage,activity_rows,rest_rows)
 coverage={}
 for c in raw_coverage:
  if c.get("resource_kind")!="activity_inventory" or c.get("availability_state") not in {"fetched","empty"}:_fail("feature_coverage_invalid")
  d=_date(c.get("local_date")); _utc(c.get("observed_at_utc"))
  if d not in need:_fail("feature_coverage_out_of_window")
  if d in coverage:_fail("feature_duplicate_coverage")
  if c.get("current_revision") is False:_fail("feature_noncurrent_coverage")
  coverage[d]=_coverage_rev(c)
 if set(coverage)!=need:_fail("feature_coverage_incomplete")
 acts=[]
 for a in activity_rows:
  _id(a);d=_date(a.get("local_date"));
  if d>end:_fail("feature_future_date")
  if start<=d<=end:
   _rev(a)
   if a.get("is_formal_training") is not True:_fail("feature_activity_classification_missing")
   acts.append(a)
 rests=[]
 for r in rest_rows:
  _id(r);_rev(r);d=_date(r.get("local_date"))
  if r.get("activity_kind")!="rest":_fail("feature_rest_invalid")
  if start<=d<=end: rests.append(r)
 output=[]
 for kind in sorted(_KINDS):
  group=rests if kind=="rest" else [a for a in acts if _kind(a.get("sport"))==kind]
  rev=tuple(sorted({*coverage.values(),*(_rev(a) for a in group)}))
  fields=(("count",None,"count"),) if kind=="rest" else (("count",None,"count"),("duration","elapsed_seconds","s"),("distance","distance_m","m"),("ascent","ascent_m","m"))
  for name,key,u in fields:
   values=[] if key is None else [_num(a[key]) for a in group if a.get(key) is not None]
   value=len(group) if key is None else sum(values) if len(values)==len(group) else None
   missing=0 if key is None else len(group)-len(values)
   sample=window_days if key is None else len(values);expected=window_days if key is None else len(group)
   output.append(DeterministicFeature(f"activity.{kind}.{name}.{window_days}d",value,f"activity.{kind}.{name}",u,start.isoformat(),end.isoformat(),sample,expected,missing,rev))
 return tuple(output)

def snapshot_metric_statistics(snapshot:StableSnapshot,*,metric:str,unit:str,end_local_date:str,window_days:int)->tuple[DeterministicFeature,...]:
 if not isinstance(snapshot,StableSnapshot) or not snapshot.subject_context or snapshot.subject_context.timezone!="Asia/Singapore":_fail("feature_snapshot_invalid")
 sid=snapshot.subject_context.subject_id; records={_id(r):r for r in _rows(snapshot.views.get("v_current_physiology_records",()))}
 coverage=_rows(snapshot.coverage); extracted=[];resources=set()
 for m in _rows(snapshot.views.get("v_current_physiology_metrics",())):
  if m.get("metric_key")!=metric:continue
  r=records.get(str(m.get("physiology_record_id")))
  if not r or r.get("subject_id")!=sid or m.get("subject_id") not in (None,sid):_fail("feature_metric_lineage_missing")
  d=r.get("local_date"); rev=_rev(r)
  resource=r.get("record_type")
  if not isinstance(resource,str) or not resource:_fail("feature_metric_lineage_missing")
  resources.add(resource)
  extracted.append({"local_date":d,"value_number":m.get("value_number"),"canonical_unit":m.get("canonical_unit"),"source_revision_id":rev,"subject_id":sid,"provider":"garmin","resource_kind":resource,"value_origin":m.get("value_origin"),"current_revision":True})
 if len(resources)!=1:_fail("feature_provider_scope_mixed")
 resource=next(iter(resources));start=_date(end_local_date)-timedelta(days=window_days-1)
 relevant=[c for c in coverage if c.get("subject_id")==sid and c.get("provider")=="garmin" and c.get("resource_kind")==resource and start<=_date(c.get("local_date"))<=_date(end_local_date)]
 return window_statistics(extracted,metric=metric,unit=unit,end_local_date=end_local_date,window_days=window_days,evidence_verified=True,coverage_rows=relevant)

def _score(p:Mapping[str,Any],a:Mapping[str,Any])->tuple[int,tuple[dict[str,Any],...]]:
 _id(p);_id(a); pd=_date(p.get("local_date"));ad=_date(a.get("local_date")); pk,ak=_kind(p.get("activity_kind")),_kind(a.get("sport")); evidence=[];score=0;possible=0
 def add(name,match,weight,**more):
  nonlocal score,possible; possible+=weight;evidence.append({"component":name,"matched":match,"weight":weight,**more});score+=weight if match else 0
 def missing(name,weight):
  nonlocal possible
  possible+=weight;evidence.append({"component":name,"matched":False,"weight":weight,"state":"missing"})
 add("date",pd==ad,25); add("sport",pk==ak,40)
 if p.get("sub_sport") is not None:add("sub_sport",p.get("sub_sport")==a.get("sub_sport"),5)
 if p.get("planned_start_time_utc") is not None:
  planned_start=_utc(p["planned_start_time_utc"])
  if a.get("start_time_utc") is None:missing("start_time",5)
  else:
   delta=abs((_utc(a["start_time_utc"])-planned_start).total_seconds())
   add("start_time",delta<=3600,5,delta_seconds=delta)
 for planned,actual,w in (("planned_duration_seconds","elapsed_seconds",15),("planned_distance_m","distance_m",10)):
  if p.get(planned) is not None:
   base=_num(p[planned])
   if base<=0:_fail("feature_measure_invalid")
   if a.get(actual) is None:missing(planned,w)
   else:
    actual_value=_num(a[actual])
    if actual_value<0:_fail("feature_measure_invalid")
    add(planned,.7<=actual_value/base<=1.3,w,ratio=actual_value/base)
 for required,actual,name in (("requires_intervals","has_intervals","interval_lap"),("requires_routes","route_count","routes"),("requires_sets","set_count","sets")):
  if p.get(required) is True:
   v=a.get(actual)
   if v is None:missing(name,10)
   else:
    match=(v is True) if actual=="has_intervals" else _num(v)>0; add(name,match,10)
 return round(100*score/possible) if possible else 0,tuple(evidence)

def match_plan_items(plan_items:Iterable[Mapping[str,Any]],activities:Iterable[Mapping[str,Any]],*,user_events:Iterable[Mapping[str,Any]]=())->tuple[dict[str,Any],...]:
 plans=sorted(_rows(plan_items),key=lambda x:_id(x)); acts=sorted(_rows(activities),key=lambda x:_id(x));events=sorted(_rows(user_events),key=lambda x:_json(x));_same_subject(plans,acts,events)
 if len(plans)>_MAX_MATCH or len(acts)>_MAX_MATCH or len({_id(x) for x in plans})!=len(plans) or len({_id(x) for x in acts})!=len(acts):_fail("feature_matching_unbounded_or_duplicate")
 if any(_kind(p.get("activity_kind")) not in _KINDS for p in plans):_fail("feature_plan_kind_invalid")
 for e in events:
  if e.get("accepted") is not True or e.get("current_revision") is not True or e.get("revoked") is True or e.get("declaration") not in {"cancelled","substituted","partial","device_not_recorded"} or isinstance(e.get("plan_item_id"),bool) or not isinstance(e.get("plan_item_id"),(str,int)):_fail("feature_event_invalid")
  _id(e);_rev(e)
 grouped={}
 for e in events:grouped.setdefault(str(e["plan_item_id"]),[]).append(e)
 if any(len(v)>1 for v in grouped.values()):_fail("feature_event_conflict")
 plan_ids={_id(p) for p in plans}
 if not set(grouped)<=plan_ids:_fail("feature_event_unknown_plan")
 cancelled={pid for pid,rows in grouped.items() if rows[0]["declaration"]=="cancelled"}
 cand={(i,j):_score(p,a) for i,p in enumerate(plans) for j,a in enumerate(acts) if _id(p) not in cancelled and _kind(p.get("activity_kind"))!="rest" and p.get("local_date")==a.get("local_date")}
 if len(cand)>50:_fail("feature_matching_unbounded_or_duplicate")
 best=-1;solutions=[]
 def walk(i,used,chosen,total):
  nonlocal best,solutions
  if i==len(plans):
   if total>best:best,solutions=total,[chosen]
   elif total==best:solutions.append(chosen)
   return
  walk(i+1,used,chosen,total)
  for j in sorted(j for ii,j in cand if ii==i and j not in used):
   if cand[i,j][0]>=25:walk(i+1,used|{j},chosen+((i,j),),total+cand[i,j][0])
 walk(0,frozenset(),(),0);chosen=min(solutions) if solutions else (); assigned=dict(chosen)
 plan_assignments={i:{dict(sol).get(i) for sol in solutions} for i in range(len(plans))}
 out=[]
 for i,p in enumerate(plans):
  explicit=grouped.get(_id(p),[]); a=acts[assigned[i]] if i in assigned else None;score,evidence=(cand[i,assigned[i]] if a else (0,()))
  if _kind(p["activity_kind"])=="rest":status="not_applicable"
  elif explicit and explicit[0]["declaration"]=="cancelled":status="not_completed_user_confirmed";a=None;score=0
  elif explicit and explicit[0]["declaration"]=="partial":status="partially_completed"
  elif explicit and explicit[0]["declaration"]=="substituted":status="substituted"
  elif explicit and explicit[0]["declaration"]=="device_not_recorded":status="unconfirmed"
  elif a:
   complete_evidence=all(x["matched"] is True for x in evidence)
   status="completed_as_planned" if _kind(p["activity_kind"])==_kind(a.get("sport")) and score>=80 and complete_evidence else "completed_modified" if _kind(p["activity_kind"])==_kind(a.get("sport")) else "substituted"
  else:status="unconfirmed"
  candidates=tuple({"activity_id":_id(acts[j]),"confidence":cand[i,j][0]/100,"component_evidence":cand[i,j][1],"activity_revision_id":_rev(acts[j]),"input_revision_ids":_activity_revisions(acts[j])} for j in sorted(j for ii,j in cand if ii==i))
  candidate_revs={r for c in candidates for r in c["input_revision_ids"]}; event_revs={_rev(e) for e in explicit}
  revs=tuple(sorted({_rev(p),*candidate_revs,*event_revs}))
  declaration=explicit[0]["declaration"] if explicit else None
  # A substitution conflicts only with strong proof that this exact plan was
  # completed.  Same-sport alone is not proof: a half-duration run is a valid
  # user-declared substitute/modified session.
  exact_completion=(a is not None and _kind(p["activity_kind"])==_kind(a.get("sport")) and score>=80 and bool(evidence) and all(x["matched"] is True for x in evidence))
  conflict=(declaration=="cancelled" and bool(candidates)) or (declaration=="device_not_recorded" and bool(candidates)) or (declaration=="substituted" and exact_completion)
  warning="user_event_conflicts_with_activity_evidence" if conflict else None
  out.append({"plan_item_id":_id(p),"activity_id":_id(a) if a and _kind(p["activity_kind"])!="rest" else None,"status":status,"confidence":score/100,"threshold":.25,"ambiguous":len(plan_assignments[i])>1 or warning is not None,"warning":warning,"candidates":candidates,"component_evidence":evidence,"window_start_local_date":p["local_date"],"window_end_local_date":p["local_date"],"input_revision_ids":revs,"plan_input_revision_id":_rev(p),"activity_input_revision_id":_rev(a) if a else None,"value_origin":VALUE_ORIGIN,"algorithm_version":FEATURE_LIBRARY_VERSION})
 return tuple(out)

def snapshot_plan_matches(snapshot:StableSnapshot,*,user_events:Iterable[Mapping[str,Any]]=())->tuple[dict[str,Any],...]:
 if not isinstance(snapshot,StableSnapshot) or not snapshot.subject_context:_fail("feature_snapshot_invalid")
 sid=snapshot.subject_context.subject_id
 plans={str(x["id"]):x for x in _rows(snapshot.views.get("v_current_training_plans",())) if x.get("subject_id")==sid}
 items=[]
 for item in _rows(snapshot.views.get("v_training_plan_items",())):
  plan=plans.get(str(item.get("training_plan_id")))
  if not plan:_fail("feature_plan_lineage_missing")
  try: prescription=json.loads(item.get("prescription_json") or "{}")
  except (TypeError,json.JSONDecodeError) as e: raise FeatureError("feature_prescription_invalid") from e
  if not isinstance(prescription,dict):_fail("feature_prescription_invalid")
  mapped={}
  for source,target in (("planned_duration_seconds","planned_duration_seconds"),("planned_distance_m","planned_distance_m"),("sub_sport","sub_sport"),("requires_intervals","requires_intervals"),("requires_routes","requires_routes"),("requires_sets","requires_sets")):
   if source in prescription:mapped[target]=prescription[source]
  if "planned_duration_minutes" in prescription:
   minutes=_num(prescription["planned_duration_minutes"])
   if minutes<=0:_fail("feature_prescription_invalid")
   minute_seconds=minutes*60
   if "planned_duration_seconds" in mapped:
    seconds=_num(mapped["planned_duration_seconds"])
    if seconds<=0 or seconds!=minute_seconds:_fail("feature_prescription_duration_ambiguous")
   mapped["planned_duration_seconds"]=minute_seconds
  items.append({**item,**mapped,"source_revision_id":plan.get("analysis_artifact_id")})
 activities=[]
 segments=_rows(snapshot.views.get("v_activity_segments",()));stages={str(x["id"]):x for x in _rows(snapshot.activity_stages)}
 for activity in _rows(snapshot.views.get("v_current_activities",())):
  if activity.get("subject_id")!=sid:_fail("feature_cross_subject")
  stage=stages.get(_id(activity));kind=_kind(activity.get("sport"));sub=re.sub(r"[^a-z0-9]","",str(activity.get("sub_sport") or "").lower())
  formal=bool(stage and activity.get("provider_state")=="active" and kind in {"running","climbing","strength"} and stage.get("summary_ready")==1 and (stage.get("fit_core_ready")==1 or stage.get("fallback_ready")==1) and sub not in {"commuting","commute","transport"})
  fit_revision=str(stage.get("active_fit_revision_id")) if stage and stage.get("active_fit_revision_id") is not None else None
  related=[s for s in segments if str(s.get("activity_id"))==_id(activity) and fit_revision is not None and str(s.get("source_revision_id"))==fit_revision]
  # A fallback proves that an activity exists, not that its FIT-only structure
  # is absent.  Conversely an active FIT with zero matching segments is useful
  # proof of zero structure and must remain in lineage.
  structure_known=fit_revision is not None
  activities.append({**activity,"is_formal_training":formal,"has_intervals":any(s.get("segment_type")=="interval" for s in related) if structure_known else None,"lap_count":sum(s.get("segment_type")=="lap" for s in related) if structure_known else None,"route_count":sum(s.get("segment_type")=="climb_active" for s in related) if structure_known else None,"set_count":sum(s.get("segment_type")=="strength_active" for s in related) if structure_known else None,"structure_revision_ids":(fit_revision,) if structure_known else ()})
 activities=[a for a in activities if a["is_formal_training"]]
 return match_plan_items(items,activities,user_events=user_events)

def adherence_statistics(matches:Iterable[Mapping[str,Any]],*,end_local_date:str,window_days:int,coverage_complete_dates:Iterable[Any],plan_applicability="plan_present",plan_revision_ids:Iterable[str|int]=())->tuple[DeterministicFeature,...]:
 if window_days not in ALLOWED_WINDOWS:_fail("feature_window_invalid")
 end=_date(end_local_date);start=end-timedelta(days=window_days-1);need={start+timedelta(days=i) for i in range(window_days)}
 coverage={}
 coverage_rows=_rows(coverage_complete_dates);match_rows=_rows(matches);_same_subject(coverage_rows,match_rows)
 for c in coverage_rows:
  if c.get("resource_kind")!="activity_inventory" or c.get("availability_state") not in {"fetched","empty"}:_fail("feature_coverage_invalid")
  d=_date(c.get("local_date"))
  if d not in need:_fail("feature_coverage_out_of_window")
  if d in coverage:_fail("feature_duplicate_coverage")
  if c.get("current_revision") is False:_fail("feature_noncurrent_coverage")
  _utc(c.get("observed_at_utc"));coverage[d]=_coverage_rev(c)
 if set(coverage)!=need:_fail("feature_coverage_incomplete")
 rows=[x for x in match_rows if start<=_date(x.get("window_end_local_date"))<=end]
 plan_revs=tuple(plan_revision_ids)
 if any(x is None or isinstance(x,bool) or not isinstance(x,(str,int)) for x in plan_revs):_fail("feature_plan_lineage_invalid")
 if plan_applicability not in {"plan_present","no_prior_plan"}:_fail("feature_plan_applicability_invalid")
 if plan_applicability=="plan_present" and not rows:_fail("feature_plan_evidence_missing")
 if plan_applicability=="no_prior_plan" and rows:_fail("feature_plan_applicability_conflict")
 allowed={"completed_as_planned","completed_modified","substituted","partially_completed","not_completed_user_confirmed","unconfirmed","not_applicable"}
 if any(x.get("status") not in allowed or not isinstance(x.get("input_revision_ids"),(list,tuple)) for x in rows):_fail("feature_adherence_invalid")
 dates=[_date(x["window_end_local_date"]) for x in rows]
 if len(dates)!=len(set(dates)):_fail("feature_duplicate_primary_date")
 if any(any(r is None or isinstance(r,bool) or not isinstance(r,(str,int)) for r in x["input_revision_ids"]) for x in rows):_fail("feature_adherence_invalid")
 rev=tuple(sorted({*coverage.values(),*(str(r) for x in rows for r in x["input_revision_ids"]),*(str(r) for r in plan_revs)}))
 confirmed=[x for x in rows if x["status"] not in {"unconfirmed","not_applicable"}]; denom=len(confirmed)
 output=[]
 for status in sorted(allowed):
  count=sum(x["status"]==status for x in rows)
  expected=len(rows);sample=sum(x["status"]!="unconfirmed" for x in rows)
  output.append(DeterministicFeature(f"plan_adherence.{status}.count.{window_days}d",count,"plan_adherence","count",start.isoformat(),end.isoformat(),sample,expected,expected-sample,rev))
  output.append(DeterministicFeature(f"plan_adherence.{status}.rate.{window_days}d",count/denom if denom and status not in {"unconfirmed","not_applicable"} else None,"plan_adherence","ratio",start.isoformat(),end.isoformat(),sample,expected,expected-sample,rev))
 output.append(DeterministicFeature(f"plan_adherence.confirmed_denominator.{window_days}d",denom,"plan_adherence","count",start.isoformat(),end.isoformat(),denom,len(rows),len(rows)-denom,rev))
 minimum=1 if plan_applicability=="no_prior_plan" or (rows and len(coverage)==window_days) else 0
 output.append(DeterministicFeature(f"plan_adherence.minimum_evidence.{window_days}d",minimum,"plan_adherence","boolean",start.isoformat(),end.isoformat(),len(rows),len(rows),0,rev))
 return tuple(output)

def quality_session_intervals(activities:Iterable[Mapping[str,Any]])->tuple[dict[str,Any],...]:
 all_rows=_rows(activities)
 if len({_id(x) for x in all_rows})!=len(all_rows):_fail("feature_duplicate_identity")
 for x in all_rows:
  _rev(x)
  if x.get("current_revision") is not True or x.get("is_formal_training") is not True:_fail("feature_interval_lineage_invalid")
  local=_date(x.get("local_date"));derived=_utc(x.get("start_time_utc")).astimezone(ZoneInfo("Asia/Singapore")).date()
  if local!=derived:_fail("feature_activity_local_date_mismatch")
 selected=sorted((x for x in all_rows if _kind(x.get("sport"))=="running" and x.get("quality_session") is True),key=lambda x:(_utc(x.get("start_time_utc")),_id(x)))
 out=[]
 for a,b in zip(selected,selected[1:]):
  h=(_utc(b["start_time_utc"])-_utc(a["start_time_utc"])).total_seconds()/3600
  if h<0:_fail("feature_interval_invalid")
  out.append({"previous_activity_id":_id(a),"activity_id":_id(b),"hours":h,"days":h/24,"window_start_local_date":a["local_date"],"window_end_local_date":b["local_date"],"input_revision_ids":tuple(sorted({_rev(a),_rev(b)})),"value_origin":VALUE_ORIGIN,"algorithm_version":FEATURE_LIBRARY_VERSION})
 return tuple(out)

def revision_impact(*,old_revision_id:str,new_revision_id:str,changed_metrics:Iterable[str],artifact_inputs:Iterable[Mapping[str,Any]],plan_inputs:Iterable[Mapping[str,Any]],subject_id: str|int|None=None,new_revision_current:bool=True)->dict[str,Any]:
 if not all(isinstance(x,str) and x for x in (old_revision_id,new_revision_id)) or old_revision_id==new_revision_id:_fail("feature_revision_invalid")
 if new_revision_current is not True:_fail("feature_revision_not_current")
 metrics=tuple(sorted({_norm(x) for x in _rows({"metric":x} for x in changed_metrics) for x in (x["metric"],)}));
 decision_revisions={old_revision_id,new_revision_id}
 def hit(rows,kind):
  out=[];context=[]
  seen=set()
  for x in _rows(rows):
   plan_id=None
   if kind=="artifact":
    artifact_id=str(x["artifact_id"]) if x.get("artifact_id") is not None else None
    run_id=str(x["analysis_run_id"]) if x.get("analysis_run_id") is not None else None
    if artifact_id is None and run_id is None:_fail("feature_lineage_identity_invalid")
    identity=artifact_id or "run:"+str(run_id)
   else:
    plan_id=_id(x,"plan_id" if x.get("plan_id") is not None else "training_plan_id");artifact_id=str(x["artifact_id"]) if x.get("artifact_id") is not None else None;run_id=str(x["analysis_run_id"]) if x.get("analysis_run_id") is not None else None;identity=plan_id
   lineage=x.get("input_revision_ids")
   if lineage is None:lineage=(x["source_revision_id"],) if x.get("source_revision_id") is not None else ()
   if not isinstance(lineage,(list,tuple)) or any(r is None or isinstance(r,bool) or not isinstance(r,(str,int)) for r in lineage):_fail("feature_lineage_invalid")
   if subject_id is not None and x.get("subject_id") not in (None,subject_id):_fail("feature_cross_subject")
   marker=(identity,tuple(map(str,lineage)),x.get("input_role"),x.get("ordinal"))
   if marker in seen:_fail("feature_duplicate_lineage")
   seen.add(marker);decision_revisions.update(map(str,lineage))
   start,end=x.get("period_start_local_date"),x.get("period_end_local_date")
   for field in ("source_window_start_utc","source_window_end_utc"):
    if x.get(field) is not None:_utc(x[field])
   if x.get("source_window_start_utc") and x.get("source_window_end_utc") and _utc(x["source_window_start_utc"])>_utc(x["source_window_end_utc"]):_fail("feature_period_invalid")
   if start is None and x.get("source_window_start_utc"):start=_utc(x["source_window_start_utc"]).astimezone(ZoneInfo("Asia/Singapore")).date().isoformat()
   if end is None and x.get("source_window_end_utc"):end=_utc(x["source_window_end_utc"]).astimezone(ZoneInfo("Asia/Singapore")).date().isoformat()
   if start is not None and end is not None and _date(start)>_date(end):_fail("feature_period_invalid")
   row_metric=_norm(str(x.get("metric",""))) if x.get("metric") is not None else None
   item={"artifact_id":artifact_id,"analysis_run_id":run_id,"plan_id":plan_id if kind=="plan" else None,"period_start_local_date":start,"period_end_local_date":end,"source_window_start_utc":x.get("source_window_start_utc"),"source_window_end_utc":x.get("source_window_end_utc"),"metric":x.get("metric"),"input_revision_ids":tuple(sorted(map(str,lineage)))}
   if str(old_revision_id) in {str(r) for r in lineage} and (not metrics or row_metric is None or row_metric in metrics):
    (out if artifact_id is not None or kind=="plan" else context).append(item)
  return tuple(sorted(out,key=_json)),tuple(sorted(context,key=_json))
 artifact_rows=_rows(artifact_inputs);plan_rows=_rows(plan_inputs);_same_subject(artifact_rows,plan_rows)
 arts,contexts=hit(artifact_rows,"artifact");plans,_=hit(plan_rows,"plan");impact="plan_review_required" if plans else "artifact_stale" if arts else "context_refresh" if contexts or metrics else "no_impact"
 all_impacts=arts+plans+contexts
 return {"old_revision_id":old_revision_id,"new_revision_id":new_revision_id,"changed_metrics":metrics,"artifact_impacts":arts,"plan_impacts":plans,"context_impacts":contexts,"impact":impact,"reason":"exact_input_revision_lineage","window_start_local_date":min((x["period_start_local_date"] for x in all_impacts if x["period_start_local_date"]),default=None),"window_end_local_date":max((x["period_end_local_date"] for x in all_impacts if x["period_end_local_date"]),default=None),"input_revision_ids":tuple(sorted(decision_revisions)),"value_origin":VALUE_ORIGIN,"algorithm_version":FEATURE_LIBRARY_VERSION}

def resolve_conflict(records:Iterable[Mapping[str,Any]])->dict[str,Any]:
 rows=sorted(_rows(records),key=_json)
 if not rows:_fail("feature_conflict_empty")
 for r in rows:
  if r.get("value_origin") not in _ORIGINS:_fail("feature_origin_invalid")
  _id(r);_rev(r)
  if not isinstance(r.get("metric"),str) or not isinstance(r.get("observed_at_utc"),str):_fail("feature_conflict_shape_invalid")
  _utc(r["observed_at_utc"])
  if isinstance(r.get("value"),float) and not math.isfinite(r["value"]):_fail("feature_number_invalid")
  _json(r.get("value"))
  for field in ("effective_from_utc","expires_at_utc"):
   if r.get(field) is not None:_utc(r[field])
  if r.get("effective_from_utc") and r.get("expires_at_utc") and _utc(r["effective_from_utc"])>=_utc(r["expires_at_utc"]):_fail("feature_effective_range_invalid")
 subjects={r.get("subject_id") for r in rows}
 if len(subjects)!=1:_fail("feature_cross_subject")
 groups={}
 for r in rows:
  if r["value_origin"]=="user_asserted":
   if r.get("scope") not in {"schedule","symptom","goal","preference"}:_fail("feature_user_scope_invalid")
   key=("user",r.get("scope"),r["metric"],r.get("effective_from_utc"),r.get("expires_at_utc"))
  else:key=("provider",r["metric"],r.get("applicable_scope"),r.get("effective_from_utc"),r.get("expires_at_utc"))
  groups.setdefault(key,[]).append(r)
 resolutions=[];blocked=[]
 for key,group in sorted(groups.items(),key=lambda x:_json(x[0])):
  numeric=[r for r in group if isinstance(r.get("value"),(int,float)) and not isinstance(r.get("value"),bool)]
  if len({r.get("unit") for r in numeric})>1:blocked.append("unit_incompatible");continue
  chosen=[]; warnings=[]
  for origin in ("provider_fact","provider_derived","provider_predicted"):
   origin_rows=[r for r in group if r["value_origin"]==origin]
   current=[r for r in origin_rows if r.get("current_revision") is True]
   if len(current)>1:blocked.append(f"multiple_current_{origin}");continue
   if current:chosen.append(current[0])
   elif origin_rows:warnings.append(f"no_current_{origin}")
  user=[r for r in group if r["value_origin"]=="user_asserted"]
  if len(user)>1 and len({_json(r["value"]) for r in user})>1:blocked.append("user_asserted_conflict");continue
  if user:chosen.append(user[0])
  derived=[r for r in group if r["value_origin"]=="derived_statistic"]
  if len(derived)>1 and len({_json(r["value"]) for r in derived})>1:blocked.append("derived_statistic_conflict");continue
  if derived:chosen.append(derived[0])
  # prior_model_output and unknown are retained only as reference records.
  resolutions.append({"conflict_key":key,"selected":tuple(dict(x) for x in chosen),"warnings":tuple(warnings)})
 if blocked:return {"status":"blocked","warning":sorted(blocked)[0],"selected":None,"resolutions":tuple(resolutions),"records":tuple(rows),"policy_version":CONFLICT_POLICY_VERSION}
 selected=tuple(x for resolution in resolutions for x in resolution["selected"])
 device=next((x for x in selected if x["value_origin"]=="provider_fact"),None)
 user=tuple(x for x in selected if x["value_origin"]=="user_asserted")
 return {"status":"resolved" if selected else "warning","warning":None if selected else "conflict_unresolved","selected":dict(selected[0]) if len(selected)==1 else None,"device_fact":dict(device) if device else None,"provider_conclusions":tuple(dict(x) for x in selected if x["value_origin"] in {"provider_derived","provider_predicted"}),"user_assertions":tuple(dict(x) for x in user),"resolutions":tuple(resolutions),"records":tuple(rows),"policy_version":CONFLICT_POLICY_VERSION,"value_origin":selected[0]["value_origin"] if len(selected)==1 else "unknown"}
class FeatureLibrary:
 version=FEATURE_LIBRARY_VERSION;stable_hash=staticmethod(stable_hash);window_statistics=staticmethod(window_statistics);activity_distribution=staticmethod(activity_distribution);snapshot_metric_statistics=staticmethod(snapshot_metric_statistics);match_plan_items=staticmethod(match_plan_items);snapshot_plan_matches=staticmethod(snapshot_plan_matches);adherence_statistics=staticmethod(adherence_statistics);quality_session_intervals=staticmethod(quality_session_intervals);revision_impact=staticmethod(revision_impact);resolve_conflict=staticmethod(resolve_conflict)
