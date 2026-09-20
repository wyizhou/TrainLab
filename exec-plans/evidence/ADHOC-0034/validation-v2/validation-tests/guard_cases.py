from pathlib import Path
import json,hashlib,importlib.util,sys,os,io,contextlib,copy
R=Path(__file__).resolve().parent.parent
F=R/'validation-tests/guard-fixture';V=F/'review';T=F/'target'
assert not F.exists(), 'Use a fresh fixture; do not overwrite earlier evidence'
F.mkdir();V.mkdir();T.mkdir()
J=lambda p:json.loads(p.read_text())
H=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,b):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
def putj(p,d):put(p,(json.dumps(d,ensure_ascii=False,indent=2)+'\n').encode())
L=J(R/'inputs/landing.json');M=J(R/'manifest.json')
for p,x in L['entries'].items():
 put(V/x['source'],(R/x['source']).read_bytes())
 if x['before'] is not None:put(T/p,(R/'inputs/before'/p).read_bytes())
putj(V/'inputs/landing.json',L)
protection={'source/fixture.txt':b'protected source\n','references/fixture.md':b'protected reference\n'}
for p,b in protection.items():put(T/p,b)
putj(V/'inputs/baseline.json',{'source_files':{p:H(T/p) for p in protection}})
old='exec-plans/evidence/old/fixture.md';put(T/old,b'old evidence\n')
putj(V/'inputs/protected-old-evidence.json',{old:{'sha256':H(T/old)}})
public=J(R/'inputs/combination-location.json')['public_states']
for p in public:
 b=(R/'Cuse'/p).read_bytes();put(T/p,b);put(V/'Cuse'/p,b)
putj(V/'inputs/combination-location.json',{'public_states':public})
status=' M source/fixture.txt\n';put(V/'inputs/Cuse-git-status.txt',status.encode())
fm={'files':{str(p.relative_to(V)):H(p) for p in V.rglob('*') if p.is_file()},'harness':M['harness']}
putj(V/'manifest.json',fm);pinned=H(V/'manifest.json')
spec=importlib.util.spec_from_file_location('under_review',R/'Cuse/exec-plans/evidence/ADHOC-0034/landing_guard.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
gitvalues={('branch','--show-current'):L['preserve_original_branch']+'\n',('rev-parse','HEAD'):L['preserve_original_head']+'\n',('diff','--cached','--name-only'):'',('status','--short','--','source'):status}
calls=[]
def git(root,*args):
 assert root==T,'must never call with original workspace';calls.append(args);return gitvalues[args]
g.git=git
results=[]
def snap():return {str(p.relative_to(T)):H(p) for p in T.rglob('*') if p.is_file()}
def run(name,reject=False,expected=None):
 before=snap();out=io.StringIO();error=None;oldcwd=Path.cwd();oldargv=sys.argv
 try:
  os.chdir(T);sys.argv=['landing_guard.py','--review',str(V),'--manifest-sha',pinned,'--apply']
  with contextlib.redirect_stdout(out):g.main()
 except (AssertionError,FileNotFoundError,IsADirectoryError,NotADirectoryError) as e:error=type(e).__name__+': '+str(e)
 finally:os.chdir(oldcwd);sys.argv=oldargv
 after=snap()
 ok=(error is not None and before==after and (expected is None or expected in error)) if reject else error is None
 result={'name':name,'expected':'reject before any install' if reject else 'apply 10; retain 116','pass':ok,'error':error,'writes':sorted(p for p in after if before.get(p)!=after[p]),'stdout':out.getvalue()}
 results.append(result)
 if not ok:print('FAIL',json.dumps(result,ensure_ascii=False))
 return result
for p,x in L['entries'].items():
 q=T/p
 if x['before'] is not None:
  original=q.read_bytes();q.write_bytes(original+b'conflict\n');run('wrong-before:'+p,True,'before');q.write_bytes(original)
  q.unlink();run('missing-before:'+p,True,'before');put(q,original)
 else:
  put(q,b'preexisting file');run('null-meets-file:'+p,True,'before');q.unlink()
  q.mkdir();run('null-meets-directory:'+p,True,'before');q.rmdir()
for p,x in L['entries'].items():
 q=V/x['source'];original=q.read_bytes();q.write_bytes(original+b'changed\n');run('wrong-after-source:'+p,True,'frozen input changed');q.write_bytes(original)
for label,mutate in [
 ('omit-existing-evidence',lambda l:l['entries'].pop(next(p for p in l['entries'] if p.startswith('exec-plans/evidence/')))),
 ('omit-0034-plan',lambda l:l['entries'].pop('exec-plans/active/ADHOC-0034-agentsmd-parallel.md')),
 ('wrong-before-metadata',lambda l:l['entries']['PLAN.md'].__setitem__('before','0'*64)),
 ('wrong-after-metadata',lambda l:l['entries']['PLAN.md'].__setitem__('after','0'*64)),
 ('retain-to-install',lambda l:l['entries']['PLAN.md'].__setitem__('action','install'))]:
 p=V/'inputs/landing.json';original=p.read_bytes();data=copy.deepcopy(L);mutate(data);putj(p,data);run(label,True,'frozen input changed');p.write_bytes(original)
for key,value in [(('branch','--show-current'),'other\n'),(('rev-parse','HEAD'),'wrong\n'),(('diff','--cached','--name-only'),'staged.txt\n'),(('status','--short','--','source'),' M source/other.txt\n')]:
 oldvalue=gitvalues[key];gitvalues[key]=value;run('git-precondition:'+' '.join(key),True);gitvalues[key]=oldvalue
for p in list(protection)+[old,public[0]]:
 q=T/p;b=q.read_bytes();q.write_bytes(b+b'changed');run('protected:'+p,True);q.write_bytes(b)
retain_inodes={p:(T/p).stat().st_ino for p,x in L['entries'].items() if x['action']=='retain'}
success=run('normal-all126')
results.append({'name':'normal-after-bytes-and-retain-no-replacement','pass':len(success['writes'])==10 and all(H(T/p)==x['after'] for p,x in L['entries'].items()) and all((T/p).stat().st_ino==ino for p,ino in retain_inodes.items())})
run('repeat-apply-with-old-before',True,'before')
report={'fixture':'Full actual 126 before/after payloads; synthetic source/reference/old-evidence protection; actual four public states; git adapter only, no Git process','guard_sha256':H(R/'Cuse/exec-plans/evidence/ADHOC-0034/landing_guard.py'),'fixture_manifest':pinned,'total':len(results),'failed':sum(not x['pass'] for x in results),'git_adapter_calls':len(calls),'results':results}
(R/'validation-evidence/guard-cases.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('SUMMARY',report['total'],report['failed']);sys.exit(bool(report['failed']))
