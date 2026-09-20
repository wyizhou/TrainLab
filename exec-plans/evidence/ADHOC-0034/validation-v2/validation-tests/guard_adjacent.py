from pathlib import Path
import importlib.util,json,hashlib,copy,os,sys,contextlib,io
R=Path(__file__).resolve().parent.parent;F=R/'validation-tests/adjacent-fixture';V=F/'review';T=F/'target'
assert not F.exists();V.mkdir(parents=True);T.mkdir()
H=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,b):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
def jput(p,d):put(p,json.dumps(d,sort_keys=True).encode())
put(T/'AGENTS.md',b'old rules');put(V/'Cuse/AGENTS.md',b'new rules');put(T/'PLAN.md',b'project plan');put(V/'Cuse/PLAN.md',b'project plan')
put(T/'source/product.txt',b'protected source');put(T/'exec-plans/evidence/old.txt',b'old evidence')
(T/'exec-plans/evidence/link').symlink_to('old.txt')
put(V/'inputs/Cuse-git-status.txt',b' M source/product.txt\n')
jput(V/'inputs/baseline.json',{'source_files':{'source/product.txt':H(T/'source/product.txt')}})
jput(V/'inputs/protected-old-evidence.json',{'exec-plans/evidence/old.txt':{'sha256':H(T/'exec-plans/evidence/old.txt')},'exec-plans/evidence/link':{'symlink':'old.txt'}})
jput(V/'inputs/combination-location.json',{'public_states':[]})
L={'preserve_original_head':'fixed-head','preserve_original_branch':'fixed-branch','entries':{'AGENTS.md':{'before':H(T/'AGENTS.md'),'after':H(V/'Cuse/AGENTS.md'),'source':'Cuse/AGENTS.md','action':'install'},'PLAN.md':{'before':H(T/'PLAN.md'),'after':H(V/'Cuse/PLAN.md'),'source':'Cuse/PLAN.md','action':'retain'}}}
spec=importlib.util.spec_from_file_location('reviewed_guard',R/'Cuse/exec-plans/evidence/ADHOC-0034/landing_guard.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
def fakegit(root,*args):
 assert root==T
 return {('branch','--show-current'):'fixed-branch',('rev-parse','HEAD'):'fixed-head',('diff','--cached','--name-only'):'',('status','--short','--','source'):' M source/product.txt\n'}[args]
g.git=fakegit
results=[]
def pin(l):
 jput(V/'inputs/landing.json',l);jput(V/'manifest.json',{'harness':['AGENTS.md'],'files':{str(p.relative_to(V)):H(p) for p in V.rglob('*') if p.is_file() and p!=V/'manifest.json'}});return H(V/'manifest.json')
def run(label,l,fail=True,token=None):
 expected=pin(l);err=None;before=H(T/'AGENTS.md')
 try:g.guard(T,V,expected if token is None else token)
 except (AssertionError,FileNotFoundError) as e:err=type(e).__name__+': '+str(e)
 results.append({'name':label,'expected_reject':fail,'error':err,'pass':(bool(err)==fail) and H(T/'AGENTS.md')==before})
run('normal-protected-symlink-identity',copy.deepcopy(L),False)
run('wrong-manifest-identity',copy.deepcopy(L),True,'0'*64)
for label,mut in [
 ('signed-wrong-before',lambda l:l['entries']['AGENTS.md'].__setitem__('before','0'*64)),
 ('signed-wrong-after',lambda l:l['entries']['AGENTS.md'].__setitem__('after','0'*64)),
 ('signed-invalid-action',lambda l:l['entries']['AGENTS.md'].__setitem__('action','overwrite')),
 ('signed-retain-unequal',lambda l:l['entries']['AGENTS.md'].__setitem__('action','retain')),
 ('signed-retain-missing-before',lambda l:l['entries']['PLAN.md'].__setitem__('before',None))]:
 l=copy.deepcopy(L);mut(l);run(label,l)
put(V/'outside-source.md',b'new rules');l=copy.deepcopy(L);l['entries']['AGENTS.md']['source']='outside-source.md';run('source-outside-Cuse',l)
put(T/'evidence.md',b'old');put(V/'Cuse/evidence.md',b'new');l=copy.deepcopy(L);l['entries']['evidence.md']={'before':H(T/'evidence.md'),'after':H(V/'Cuse/evidence.md'),'source':'Cuse/evidence.md','action':'install'};run('install-outside-allowlist',l)
q=T/'PLAN.md';b=q.read_bytes();q.unlink();q.symlink_to('evidence.md');run('target-symlink-refused',copy.deepcopy(L));q.unlink();q.write_bytes(b)
q=T/'exec-plans/evidence/link';q.unlink();q.symlink_to('other.txt');run('old-link-identity-changed',copy.deepcopy(L));q.unlink();q.symlink_to('old.txt')
# Exercise the explicitly documented future-evidence protocol, not a nonexistent append API.
append=json.loads((R/'inputs/landing.json').read_text())['append_only_evidence']
for path in append['files']+[x+'synthetic-future.json' for x in append['prefixes']]:
 q=T/path;q.parent.mkdir(parents=True,exist_ok=True)
 with q.open('xb') as f:f.write(b'first evidence')
 err=None
 try:
  with q.open('xb') as f:f.write(b'overwrite')
 except FileExistsError:err='FileExistsError'
 results.append({'name':'future-evidence-exclusive-create:'+path,'pass':err is not None and q.read_bytes()==b'first evidence','method':'Python xb protocol required by handoff; not real future evidence creation'})
report={'cases':results,'total':len(results),'failed':sum(not x['pass'] for x in results)}
(R/'validation-evidence/guard-adjacent.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2));sys.exit(bool(report['failed']))
