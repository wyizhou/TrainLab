from pathlib import Path
import hashlib,json,collections,sys
root=Path(__file__).resolve().parent.parent
m=root/'manifest.json'
expected='17c0becf800d820b02d5ac824a05891b4379b0070cdbf0d660397a0063b36f1d'
assert hashlib.sha256(m.read_bytes()).hexdigest()==expected
files=json.loads(m.read_text())['files']
allowed_states={'states/Goal-example.md','states/activities/.gitkeep','states/health/.gitkeep','states/verification/.gitkeep'}
errors=[]
for n,h in files.items():
 p=root/n
 if n.startswith(('C34/states/','Cuse/states/')) and n.split('/',1)[1] not in allowed_states: errors.append('unauthorized state '+n);continue
 if p.is_symlink() or not p.is_file(): errors.append('missing/type '+n);continue
 if hashlib.sha256(p.read_bytes()).hexdigest()!=h: errors.append('hash '+n)
actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and str(p.relative_to(root)).split('/')[0] not in {'validation-tests','validation-evidence'} and p!=m}
errors += ['extra '+n for n in actual-set(files)]+['missing '+n for n in set(files)-actual]
links=[str(p.relative_to(root)) for p in root.rglob('*') if p.is_symlink() and str(p.relative_to(root)).split('/')[0] not in {'validation-tests','validation-evidence'}]
assert not links
result={'manifest':expected,'files':len(files),'counts':dict(collections.Counter(n.split('/')[0] if '/' in n else 'root' for n in files)),'errors':errors,'symlinks':links,'git_present':(root/'.git').exists()}
print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(bool(errors))
