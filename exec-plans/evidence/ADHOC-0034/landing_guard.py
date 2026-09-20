from pathlib import Path
import argparse,hashlib,json,subprocess,os,tempfile

def sha(p):
 return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def readj(p):
 return json.loads(Path(p).read_text())
def git(root,*args):
 return subprocess.check_output(['git','-C',str(root),*args],text=True)
def guard(root,review,expected):
 assert sha(review/'manifest.json')==expected,'manifest identity'
 manifest=readj(review/'manifest.json')
 assert all(sha(review/p)==h for p,h in manifest['files'].items()),'frozen input changed'
 landing=readj(review/'inputs/landing.json');base=readj(review/'inputs/baseline.json')
 assert git(root,'branch','--show-current').strip()==landing['preserve_original_branch']
 assert git(root,'rev-parse','HEAD').strip()==landing['preserve_original_head']
 assert not git(root,'diff','--cached','--name-only'),'staging changed'
 for p,x in landing['entries'].items():
  q=root/p;assert not q.is_symlink(),p
  assert (not q.exists()) if x['before'] is None else (q.is_file() and sha(q)==x['before']),('before',p)
  assert sha(review/x['source'])==x['after'],('after source',p)
  assert (review/x['source']).is_relative_to(review/'Cuse'),p
  if x['action']=='retain':assert x['before']==x['after'],p
  else:assert x['action']=='install' and p in set(manifest['harness'])|{'PLAN.md','MEMORY.md','exec-plans/active/ADHOC-0033-ai-coach.md','exec-plans/active/ADHOC-0034-agentsmd-parallel.md'},p
 protected(root,review,base)
 return landing,base

def protected(root,review,base):
 assert all(sha(root/p)==h for p,h in base['source_files'].items()),'source/reference changed'
 for p,item in readj(review/'inputs/protected-old-evidence.json').items():
  if 'symlink' in item:assert (root/p).is_symlink() and str((root/p).readlink())==item['symlink'],p
  else:assert sha(root/p)==item['sha256'],p
 for p in readj(review/'inputs/combination-location.json')['public_states']:
  assert sha(root/p)==sha(review/'Cuse'/p),p
 current=[x for x in git(root,'status','--short','--','source').splitlines()]
 expected=[x for x in (review/'inputs/Cuse-git-status.txt').read_text().splitlines() if x[3:].startswith('source/')]
 assert current==expected,'source statuses changed'
 assert not git(root,'diff','--cached','--name-only')

def main():
 a=argparse.ArgumentParser();a.add_argument('--review',type=Path,required=True);a.add_argument('--manifest-sha',required=True);a.add_argument('--apply',action='store_true');args=a.parse_args();root=Path.cwd();review=args.review.resolve();landing,base=guard(root,review,args.manifest_sha);written=[]
 if args.apply:
  for p,x in landing['entries'].items():
   if x['action']=='retain':continue
   q=root/p;assert (not q.exists()) if x['before'] is None else (q.is_file() and sha(q)==x['before']),p;q.parent.mkdir(parents=True,exist_ok=True)
   data=(review/x['source']).read_bytes();fd,temp=tempfile.mkstemp(prefix='.'+q.name+'.adhoc0034-',dir=q.parent)
   with os.fdopen(fd,'wb') as f:f.write(data)
   assert sha(temp)==x['after']
   os.replace(temp,q);assert sha(q)==x['after'];written.append(p)
  assert all(sha(root/p)==x['after'] for p,x in landing['entries'].items())
  protected(root,review,base)
 print(json.dumps({'mode':'apply' if args.apply else 'dry-run','targets':len(landing['entries']),'install_count':sum(x['action']=='install' for x in landing['entries'].values()),'written':written,'original_source_and_history_preserved':True,'staging_empty':True,'manifest_sha256':args.manifest_sha},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
