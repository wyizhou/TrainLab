from pathlib import Path
import hashlib,json,difflib,re,collections,sys
R=Path(__file__).resolve().parent.parent
J=lambda p:json.loads((R/p).read_text())
H=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
M=J('manifest.json');L=J('inputs/landing.json');B=J('inputs/baseline.json');D=J('inputs/developer-baseline.json');U=J('inputs/upstream.json');E=J('inputs/protected-old-evidence.json')
checks=[]
def check(name,ok,detail=None):
 checks.append({'name':name,'pass':bool(ok),'detail':detail});print(('PASS ' if ok else 'FAIL ')+name,detail if detail is not None else '')
def files(base): return {str(p.relative_to(base)) for p in base.rglob('*') if p.is_file()}
check('upstream11',len(U['files'])==11 and all(H(R/'inputs/upstream'/p)==h for p,h in U['files'].items()),U['head'])
orig=set(M['harness'])-{'skills/README.md'}
check('two_combinations_seven_originals',all((R/c/p).read_bytes()==(R/'inputs/upstream'/p).read_bytes() for c in ['C34','Cuse'] for p in orig))
check('H_equal8',len(M['harness'])==8 and all(H(R/c/p)==h for c in ['C34','Cuse'] for p,h in M['harness'].items()))
check('protected179',len(B['source_files'])==179 and all(H(R/'Cuse'/p)==h for p,h in B['source_files'].items()))
oldnormal={p:x for p,x in E.items() if 'sha256' in x};oldlinks={p:x for p,x in E.items() if 'symlink' in x}
check('old_evidence6231',len(oldnormal)==6231 and all(H(R/'Cuse'/p)==x['sha256'] for p,x in oldnormal.items()))
check('oldlinks3_identity_only',len(oldlinks)==3 and all(not (R/'Cuse'/p).exists() for p in oldlinks) and all(x['symlink']==J('inputs/combination-location.json')['excluded_legacy_environment_links'][p]['symlink'] for p,x in oldlinks.items()))
changed=[p for p,h in D['files'].items() if not (R/'C34'/p).is_file() or H(R/'C34'/p)!=h]
new=files(R/'C34')-set(D['files'])
check('C34_delta_allowed',set(changed)<=set(M['harness'])|{'PLAN.md','MEMORY.md','exec-plans/active/ADHOC-0034-agentsmd-parallel.md'} and all(p in M['harness'] or p.startswith('exec-plans/evidence/ADHOC-0034/') for p in new),{'changed':changed,'new':sorted(new)})
check('C34_product_baseline',all(H(R/'C34'/p)==h for p,h in D['files'].items() if p.startswith('source/')) and not (R/'C34/exec-plans/active/ADHOC-0033-ai-coach.md').exists())
entries=L['entries']; core=set(M['harness'])|{'PLAN.md','MEMORY.md','exec-plans/active/ADHOC-0033-ai-coach.md','exec-plans/active/ADHOC-0034-agentsmd-parallel.md'}
ev={p for p in files(R/'Cuse') if p.startswith('exec-plans/evidence/ADHOC-0034/')}
check('landing_exhaustive126',len(entries)==126 and set(entries)==core|ev,{'core':len(core),'evidence':len(ev),'missing':sorted((core|ev)-set(entries)),'extra':sorted(set(entries)-(core|ev))})
check('before_exact125',files(R/'inputs/before')=={p for p,x in entries.items() if x['before'] is not None} and all(H(R/'inputs/before'/p)==x['before'] if x['before'] is not None else not (R/'inputs/before'/p).exists() for p,x in entries.items()))
check('after_exact126',all(x['source']=='Cuse/'+p and H(R/x['source'])==x['after'] for p,x in entries.items()))
check('install10_retain116',collections.Counter(x['action'] for x in entries.values())=={'install':10,'retain':116} and all((x['action']=='install')==(x['before']!=x['after']) for x in entries.values()),[p for p,x in entries.items() if x['action']=='install'])
check('new_skill_null_only',[p for p,x in entries.items() if x['before'] is None]==['skills/web-browser-acceptance/SKILL.md'])
check('append_scope_no_existing',all(not any(p.startswith(q) for p in entries) for q in L['append_only_evidence']['prefixes']) and not(set(L['append_only_evidence']['files'])&set(entries)),L['append_only_evidence'])
patch=''
for p,x in entries.items():
 if x['action']=='install':
  a=(R/'inputs/before'/p).read_text().splitlines(True) if x['before'] else []
  b=(R/'Cuse'/p).read_text().splitlines(True)
  patch+=''.join(difflib.unified_diff(a,b,fromfile='before/'+p,tofile='Cuse/'+p))
(R/'validation-evidence/generated-landing.patch').write_text(patch)
check('exact_landing_delta',patch==(R/'inputs/landing-delta.patch').read_text())
recorddiff=''
for combo,baseline in [('C34','baseline-C34'),('Cuse','history-baseline-Cuse')]:
 for p in sorted(files(R/'inputs'/baseline)):
  if not p.endswith('.md'):continue
  a=(R/'inputs'/baseline/p).read_text().splitlines(True);b=(R/combo/p).read_text().splitlines(True)
  delta=list(difflib.unified_diff(a,b,fromfile=baseline+'/'+p,tofile=combo+'/'+p));recorddiff+=''.join(delta)
  removed=[s for s in delta if s.startswith('-') and not s.startswith('---')]
  if p=='MEMORY.md': check(combo+'_memory_only_harness',len(removed)==1 and removed[0].startswith('-| 当前脚手架 |'))
  if p.endswith('ADHOC-0033-ai-coach.md'):check('0033_only_added',not removed)
(R/'validation-evidence/record-deltas.patch').write_text(recorddiff)
status=(R/'inputs/Cuse-git-status.txt').read_text().splitlines();source=[s for s in status if s[3:].startswith('source/')]
check('source_status38',len(source)==38 and collections.Counter(s[:2] for s in source)=={' M':15,'??':23},dict(collections.Counter(s[:2] for s in source)))
patchtext=(R/'inputs/Cuse-git-diff.patch').read_text();sections=re.split(r'(?=^diff --git )',patchtext,flags=re.M)
verified=[]
for section in sections:
 match=re.match(r'diff --git a/(source/\S+) b/(source/\S+)',section)
 if not match:continue
 p=match[2];lines=section.splitlines(True);content=(R/'Cuse'/p).read_text().splitlines(True)
 for i,line in enumerate(lines):
  mat=re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@',line)
  if not mat:continue
  after=[]
  for nxt in lines[i+1:]:
   if nxt.startswith(('@@','diff --git')):break
   if nxt.startswith((' ','+')):after.append(nxt[1:])
  start=int(mat[1])-1
  check('source_diff_hunk:'+p+':'+str(start+1),content[start:start+len(after)]==after)
 verified.append(p)
check('source_15_modified_patch',len(verified)==15 and set(verified)=={s[3:] for s in source if s[:2]==' M'})
check('source23_untracked_bytes',all(s[3:] in B['source_files'] and H(R/'Cuse'/s[3:])==B['source_files'][s[3:]] for s in source if s[:2]=='??'))
(R/'validation-evidence/audit.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2));print('SUMMARY',len(checks),sum(not x['pass'] for x in checks));sys.exit(any(not x['pass'] for x in checks))
