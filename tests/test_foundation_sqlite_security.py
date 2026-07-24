from __future__ import annotations

from pathlib import Path
import sqlite3
import os
import stat
import itertools
import hashlib
import pytest

import trainlab.foundation as foundation
from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool, IncompatibleError


UTC="2026-07-24T00:00:00Z"

def _tool(root:Path)->FoundationTool:
 return FoundationTool(FoundationConfig(root,root/'data.db',root/'raw',root/'state',root/'state'/'foundation-ready.json',root/'state'/'locks'/'foundation.lock'))

def _custom_tool(root:Path)->FoundationTool:
 return FoundationTool(FoundationConfig(root,root/'custom.sqlite',root/'raw',root/'state',root/'state'/'foundation-ready.json',root/'state'/'locks'/'foundation.lock'))

def test_canonical_wal_and_no_private_sqlite_proxy(tmp_path:Path)->None:
 root=tmp_path/'f'; tool=_tool(root); assert tool.execute(FoundationRequest('init','sqlite-security',UTC)).status=='initialized'
 conn=tool._connect(root/'data.db');
 try:
  assert conn.execute('PRAGMA journal_mode').fetchone()[0].lower()=='wal'
 finally: conn.close()
 assert not list(root.rglob('.foundation-sqlite-*'))

def test_connection_close_never_removes_canonical_replacement(tmp_path:Path)->None:
 root=tmp_path/'f'; tool=_tool(root); assert tool.execute(FoundationRequest('init','sqlite-close',UTC)).status=='initialized'
 conn=tool._connect(root/'data.db'); replacement=root/'replacement.db'; sqlite3.connect(replacement).close(); root.joinpath('data.db').replace(root/'old.db'); replacement.replace(root/'data.db'); conn.close()
 assert (root/'data.db').exists()

def test_readonly_observes_committed_uncheckpointed_wal(tmp_path:Path)->None:
 root=tmp_path/'f'; tool=_tool(root); assert tool.execute(FoundationRequest('init','sqlite-wal',UTC)).status=='initialized'
 writer=tool._connect(root/'data.db')
 try:
  writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE wal_probe(value INTEGER)'); writer.execute('INSERT INTO wal_probe VALUES(42)')
  assert (root/'data.db-wal').stat().st_size>0
  reader=tool._connect(root/'data.db',readonly=True)
  try: assert reader.execute('SELECT value FROM wal_probe').fetchone()[0]==42
  finally: reader.close()
 finally: writer.close()

def test_create_failure_with_same_inode_content_mutation_leaves_blocker(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 root=tmp_path/'f'; root.mkdir(mode=0o700); tool=_tool(root); original=os.fsync; original_open=os.open; done=False; dbfd=-1
 def opened(name,flags,*args,**kwargs):
  nonlocal dbfd
  value=original_open(name,flags,*args,**kwargs)
  if name=='data.db' and flags&os.O_CREAT and flags&os.O_EXCL: dbfd=value
  return value
 def mutate_then_fail(fd:int)->None:
  nonlocal done
  if fd==dbfd and not done:
   done=True; os.ftruncate(fd,0); os.write(fd,b'unknown-external-content'); raise OSError('fsync')
  original(fd)
 monkeypatch.setattr(os,'open',opened); monkeypatch.setattr(os,'fsync',mutate_then_fail)
 with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(root/'data.db')
 assert not (root/'data.db').exists()
 claims=list(root.glob('.data.db.create-cleanup-*')); assert len(claims)==1 and claims[0].read_bytes()==b'unknown-external-content'
 monkeypatch.setattr(os,'fsync',original)
 with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(root/'data.db')

@pytest.mark.parametrize('kind',["fstat","fchmod","file_fsync","parent_fsync"])
def test_c1a_precise_create_failure_leaves_blocker(tmp_path:Path,monkeypatch:pytest.MonkeyPatch,kind:str)->None:
 root=tmp_path/'f'; root.mkdir(mode=0o700); tool=_tool(root); original_open=os.open; original_stat=os.fstat; original_chmod=os.fchmod; original_fsync=os.fsync; dbfd=-1; fired=False
 def tracked_open(name,flags,*args,**kwargs):
  nonlocal dbfd
  result=original_open(name,flags,*args,**kwargs)
  if name=='data.db' and flags & os.O_CREAT and flags & os.O_EXCL: dbfd=result
  return result
 def bad_stat(fd:int):
  nonlocal fired
  if kind=='fstat' and fd==dbfd and not fired: fired=True; raise OSError('fstat')
  return original_stat(fd)
 def bad_chmod(fd:int,mode:int):
  nonlocal fired
  if kind=='fchmod' and fd==dbfd and not fired: fired=True; raise OSError('chmod')
  return original_chmod(fd,mode)
 def bad_fsync(fd:int):
  nonlocal fired
  mode=original_stat(fd).st_mode
  if kind=='file_fsync' and fd==dbfd and stat.S_ISREG(mode) and not fired: fired=True; raise OSError('file')
  if kind=='parent_fsync' and stat.S_ISDIR(mode) and not fired: fired=True; raise OSError('parent')
  return original_fsync(fd)
 monkeypatch.setattr(os,'open',tracked_open); monkeypatch.setattr(os,'fstat',bad_stat); monkeypatch.setattr(os,'fchmod',bad_chmod); monkeypatch.setattr(os,'fsync',bad_fsync)
 with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(root/'data.db')


@pytest.mark.parametrize('kind',["fstat","fchmod","file_fsync","parent_fsync"])
def test_c1af_create_failure_fd_loop(tmp_path:Path,kind:str)->None:
 baseline=len(list(Path('/dev/fd').iterdir()))
 for index in range(20):
  root=tmp_path/f'{kind}-{index}'/'f'; root.parent.mkdir(); root.mkdir(mode=0o700); tool=_tool(root); dbfd=-1; fired=False
  with pytest.MonkeyPatch.context() as monkey:
   original_open=os.open; original_stat=os.fstat; original_chmod=os.fchmod; original_fsync=os.fsync
   def opened(name,flags,*args,**kwargs):
    nonlocal dbfd
    value=original_open(name,flags,*args,**kwargs)
    if name=='data.db' and flags&os.O_CREAT and flags&os.O_EXCL: dbfd=value
    return value
   def fst(fd):
    nonlocal fired
    if kind=='fstat' and fd==dbfd and not fired: fired=True; raise OSError('fstat')
    return original_stat(fd)
   def fch(fd,mode):
    nonlocal fired
    if kind=='fchmod' and fd==dbfd and not fired: fired=True; raise OSError('fchmod')
    return original_chmod(fd,mode)
   def fsy(fd):
    nonlocal fired
    mode=original_stat(fd).st_mode
    if ((kind=='file_fsync' and fd==dbfd and stat.S_ISREG(mode)) or (kind=='parent_fsync' and stat.S_ISDIR(mode))) and not fired: fired=True; raise OSError(kind)
    return original_fsync(fd)
   monkey.setattr(os,'open',opened); monkey.setattr(os,'fstat',fst); monkey.setattr(os,'fchmod',fch); monkey.setattr(os,'fsync',fsy)
   with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(root/'data.db')
   assert fired and dbfd>=0 and not (root/'data.db').exists() and len(list(root.glob('.data.db.create-cleanup-*')))==1
 assert len(list(Path('/dev/fd').iterdir())) <= baseline+1

@pytest.mark.parametrize('case',["same_inode","different_inode","rename_error","claim_mutation"])
def test_c1b_real_create_cleanup_races(tmp_path:Path,monkeypatch:pytest.MonkeyPatch,case:str)->None:
 root=tmp_path/'f'; root.mkdir(mode=0o700); tool=_tool(root); oo=os.open; of=os.fsync; orename=os.rename; dbfd=-1; created_inode=None; fired=False; mutated=False; rename_fired=False
 def opened(name,flags,*a,**k):
  nonlocal dbfd,created_inode
  value=oo(name,flags,*a,**k)
  if name=='data.db' and flags&os.O_CREAT and flags&os.O_EXCL: dbfd=value; created_inode=(os.fstat(value).st_dev,os.fstat(value).st_ino)
  return value
 def fsync(fd):
  nonlocal fired
  if fd==dbfd and not fired:
   fired=True
   if case=='same_inode': os.ftruncate(fd,0); os.write(fd,b'unknown')
   if case=='different_inode':
    other=root/'other'; other.write_bytes(b'other'); other.chmod(0o600); os.replace(other,root/'data.db')
   raise OSError('file-fsync')
  return of(fd)
 def renamed(src,dst,*a,**k):
  nonlocal mutated,rename_fired
  if case=='rename_error' and src=='data.db' and '.create-cleanup-' in dst: rename_fired=True; raise OSError('rename')
  result=orename(src,dst,*a,**k)
  if case=='claim_mutation' and '.create-cleanup-' in dst and not mutated:
   mutated=True; p=root/dst; p.write_bytes(b'unknown')
  return result
 monkeypatch.setattr(os,'open',opened); monkeypatch.setattr(os,'fsync',fsync); monkeypatch.setattr(os,'rename',renamed)
 with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(root/'data.db')
 assert fired and dbfd>=0 and created_inode is not None
 claims=list(root.glob('.data.db.create-*')); assert claims
 if case=='same_inode':
  assert not (root/'data.db').exists() and any(item.read_bytes()==b'unknown' for item in claims)
 elif case=='different_inode':
  evidence=[item for item in [root/'data.db',*claims] if item.exists() and item.read_bytes()==b'other']
  assert evidence and all((item.stat().st_dev,item.stat().st_ino)!=created_inode for item in evidence)
 elif case=='rename_error':
  assert rename_fired and (root/'data.db').exists() and list(root.glob('.data.db.create-intent-*'))
 else:
  assert mutated and any(item.read_bytes()==b'unknown' for item in claims)
 monkeypatch.setattr(os,'open',oo); monkeypatch.setattr(os,'fsync',of); monkeypatch.setattr(os,'rename',orename)
 with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(root/'data.db')

def test_c1b_completion_final_fsync_fallback_rename_blocker(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 root=tmp_path/'f'; root.mkdir(mode=0o700); tool=_tool(root); oo=os.open; of=os.fsync; olink=os.link; orename=os.rename; dbfd=-1; created=None; parent_calls=0; final_fired=False; link_fired=False; fallback_fired=False
 def opened(name,flags,*a,**k):
  nonlocal dbfd,created
  value=oo(name,flags,*a,**k)
  if name=='data.db' and flags&os.O_CREAT and flags&os.O_EXCL: dbfd=value; info=os.fstat(value); created=(info.st_dev,info.st_ino)
  return value
 def fsync(fd):
  nonlocal parent_calls,final_fired
  if stat.S_ISDIR(os.fstat(fd).st_mode):
   parent_calls+=1
   if parent_calls==4: final_fired=True; raise OSError('final-parent-fsync')
  return of(fd)
 def linked(src,dst,*a,**k):
  nonlocal link_fired
  if 'create-intent-post-fsync' in dst and not link_fired: link_fired=True; raise OSError('link')
  return olink(src,dst,*a,**k)
 def renamed(src,dst,*a,**k):
  nonlocal fallback_fired
  if src=='data.db' and 'create-intent-post-fsync' in dst: fallback_fired=True
  return orename(src,dst,*a,**k)
 monkeypatch.setattr(os,'open',opened); monkeypatch.setattr(os,'fsync',fsync); monkeypatch.setattr(os,'link',linked); monkeypatch.setattr(os,'rename',renamed)
 with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(root/'data.db')
 assert final_fired and link_fired and fallback_fired and created is not None and not (root/'data.db').exists()
 claims=list(root.glob('.data.db.create-intent-post-fsync-*')); assert len(claims)==1 and (claims[0].stat().st_dev,claims[0].stat().st_ino)==created and claims[0].read_bytes()==b''
 monkeypatch.setattr(os,'open',oo); monkeypatch.setattr(os,'fsync',of); monkeypatch.setattr(os,'link',olink); monkeypatch.setattr(os,'rename',orename)
 with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(root/'data.db')

def test_c1b_normal_create_leaves_no_intent_or_cleanup(tmp_path:Path)->None:
 root=tmp_path/'f'; root.mkdir(mode=0o700); conn=_tool(root)._connect(root/'data.db'); conn.close()
 assert not list(root.glob('.data.db.create-intent-*')) and not list(root.glob('.data.db.create-cleanup-*'))

@pytest.mark.parametrize('case,iteration',list(itertools.product(["claim_new_inode","claim_open","claim_after_stat","unlink","unlink_fsync"],range(20))))
def test_c1b2_persisted_cleanup_failures_block(tmp_path:Path,monkeypatch:pytest.MonkeyPatch,case:str,iteration:int)->None:
 baseline=len(list(Path('/dev/fd').iterdir()))
 root=tmp_path/f'{case}-{iteration}'/'f'; root.parent.mkdir(); root.mkdir(mode=0o700); tool=_tool(root); oo=os.open; os0=os.stat; of=os.fsync; ou=os.unlink; orename=os.rename; dbfd=-1; persisted=False; stages:set[str]=set(); claimed=''; claim_stats=0; intent_inode=None; replacement_inode=None
 def opened(name,flags,*a,**k):
  nonlocal dbfd
  if case=='claim_open' and '.create-cleanup-' in str(name): stages.add('claim_open'); raise OSError('claim-open')
  value=oo(name,flags,*a,**k)
  if name=='data.db' and flags&os.O_CREAT and flags&os.O_EXCL: dbfd=value
  return value
 def fsync(fd):
  nonlocal persisted
  if fd==dbfd: return of(fd)
  if stat.S_ISDIR(os.fstat(fd).st_mode):
   if not persisted: persisted=True; return of(fd)
   if case=='unlink_fsync' and 'cleanup_unlink' in stages: stages.add('post_unlink_fsync'); raise OSError('unlink-fsync')
  return of(fd)
 def stated(name,*a,**k):
  nonlocal claim_stats
  text=str(name)
  if text=='data.db' and persisted and 'checked_stat_fail' not in stages: stages.add('checked_stat_fail'); raise OSError('checked-stat')
  if '.create-cleanup-' in text:
   claim_stats+=1
   if case=='claim_after_stat' and claim_stats>=2: stages.add('claim_after_stat'); raise OSError('claim-after-stat')
  return os0(name,*a,**k)
 def renamed(src,dst,*a,**k):
  nonlocal claimed,replacement_inode
  result=orename(src,dst,*a,**k)
  if '.create-cleanup-' in dst:
   claimed=dst
   if case=='claim_new_inode':
    other=root/'other'; other.write_bytes(b''); other.chmod(0o600); os.replace(other,root/dst); replacement_inode=(root/dst).stat().st_ino; stages.add('claim_new_inode')
  return result
 def unlinked(name,*a,**k):
  if '.create-cleanup-' in name: stages.add('cleanup_unlink')
  if case=='unlink' and '.create-cleanup-' in name: stages.add('cleanup_unlink_error'); raise OSError('unlink')
  return ou(name,*a,**k)
 monkeypatch.setattr(os,'open',opened); monkeypatch.setattr(os,'stat',stated); monkeypatch.setattr(os,'fsync',fsync); monkeypatch.setattr(os,'rename',renamed); monkeypatch.setattr(os,'unlink',unlinked)
 with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(root/'data.db')
 monkeypatch.setattr(os,'open',oo); monkeypatch.setattr(os,'stat',os0); monkeypatch.setattr(os,'fsync',of); monkeypatch.setattr(os,'rename',orename); monkeypatch.setattr(os,'unlink',ou)
 expected={'claim_new_inode':'claim_new_inode','claim_open':'claim_open','claim_after_stat':'claim_after_stat','unlink':'cleanup_unlink_error','unlink_fsync':'post_unlink_fsync'}[case]
 intents=list(root.glob('.data.db.create-intent-*')); assert 'checked_stat_fail' in stages and expected in stages and len(intents)==1
 intent_inode=intents[0].stat().st_ino; assert intents[0].stat().st_mode & 0o777==0o600 and intents[0].read_bytes()==b''
 if case=='claim_new_inode':
  claims=list(root.glob('.data.db.create-cleanup-*')); assert not (root/'data.db').exists() and len(claims)==1 and claims[0].read_bytes()==b'' and claims[0].stat().st_mode&0o777==0o600 and claims[0].stat().st_ino==replacement_inode and replacement_inode!=intent_inode
 elif case=='unlink_fsync': assert not (root/'data.db').exists() and not list(root.glob('.data.db.create-cleanup-*'))
 else:
  claims=list(root.glob('.data.db.create-cleanup-*')); assert not (root/'data.db').exists() and len(claims)==1 and claims[0].read_bytes()==b'' and claims[0].stat().st_mode&0o777==0o600 and claims[0].stat().st_ino==intent_inode
 with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(root/'data.db')
 assert len(list(Path('/dev/fd').iterdir())) <= baseline+1

@pytest.mark.parametrize('readonly',[False,True])
def test_c2_connect_window_db_replacement_is_rejected(tmp_path:Path,monkeypatch:pytest.MonkeyPatch,readonly:bool)->None:
 root=tmp_path/'f'; tool=_tool(root); assert tool.execute(FoundationRequest('init','c2-race',UTC)).status=='initialized'
 writer=None
 if readonly:
  writer=tool._connect(root/'data.db'); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE c2_wal(v)'); writer.execute('INSERT INTO c2_wal VALUES(1)')
 original=sqlite3.connect; fired=False
 def swapped(*a,**k):
  nonlocal fired
  value=original(*a,**k)
  if not fired:
   fired=True; other=root/'other.db'; original(other).close(); other.chmod(0o600); os.replace(other,root/'data.db')
  return value
 monkeypatch.setattr(sqlite3,'connect',swapped)
 with pytest.raises(IncompatibleError,match='sqlite_path_replaced'): tool._connect(root/'data.db',readonly=readonly)
 assert fired and (root/'data.db').exists()
 if writer: writer.close()

def test_c2_connect_failure_fd_loop(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 root=tmp_path/'f'; tool=_tool(root); assert tool.execute(FoundationRequest('init','c2-fd',UTC)).status=='initialized'; original=sqlite3.connect; baseline=len(list(Path('/dev/fd').iterdir()))
 def fail(*a,**k): raise sqlite3.OperationalError('connect')
 monkeypatch.setattr(sqlite3,'connect',fail)
 for _ in range(20):
  with pytest.raises(sqlite3.OperationalError): tool._connect(root/'data.db')
 assert len(list(Path('/dev/fd').iterdir()))<=baseline+1

@pytest.mark.parametrize('mutation,iteration',list(itertools.product(["replace","unlink","symlink","mode","directory"],range(20))))
def test_c2_nonempty_wal_post_connect_mutations_fail_closed(tmp_path:Path,monkeypatch:pytest.MonkeyPatch,mutation:str,iteration:int)->None:
 root=tmp_path/f'f-{iteration}'; tool=_tool(root); assert tool.execute(FoundationRequest('init',f'c2-wal-race-{iteration}',UTC)).status=='initialized'; writer=tool._connect(root/'data.db'); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE c2_mut(v)'); writer.execute('INSERT INTO c2_mut VALUES(1)'); baseline=len(list(Path('/dev/fd').iterdir()))
 original=sqlite3.connect; fired=False; wal=root/'data.db-wal'
 def mutate(*a,**k):
  nonlocal fired
  value=original(*a,**k)
  if not fired:
   fired=True
   if mutation=='replace': other=root/'other-wal'; other.write_bytes(wal.read_bytes()); other.chmod(0o600); os.replace(other,wal)
   elif mutation=='unlink': wal.unlink()
   elif mutation=='symlink': wal.unlink(); wal.symlink_to(root/'elsewhere')
   elif mutation=='mode': wal.chmod(0o644)
   else: wal.unlink(); wal.mkdir()
  return value
 monkeypatch.setattr(sqlite3,'connect',mutate)
 with pytest.raises(IncompatibleError,match='sqlite_(wal_state_unsafe|path_unsafe)'): tool._connect(root/'data.db',readonly=True)
 assert fired
 writer.close()
 assert len(list(Path('/dev/fd').iterdir()))<=baseline+1

@pytest.mark.parametrize('readonly,mutation,iteration',list(itertools.product([False,True],["replace","unlink","symlink","mode","directory"],range(20))))
def test_c2_db_post_connect_mutations_fail_closed(tmp_path:Path,monkeypatch:pytest.MonkeyPatch,readonly:bool,mutation:str,iteration:int)->None:
 root=tmp_path/f'f-{iteration}'; tool=_tool(root); assert tool.execute(FoundationRequest('init',f'c2-db-race-{iteration}',UTC)).status=='initialized'; writer=None; baseline=len(list(Path('/dev/fd').iterdir()))
 if readonly:
  writer=tool._connect(root/'data.db'); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE c2_db(v)'); writer.execute('INSERT INTO c2_db VALUES(1)')
 original=sqlite3.connect; fired=False
 def mutate(*a,**k):
  nonlocal fired
  conn=original(*a,**k)
  if not fired:
   fired=True; db=root/'data.db'
   if mutation=='replace': other=root/'other'; original(other).close(); other.chmod(0o600); os.replace(other,db)
   elif mutation=='unlink': db.unlink()
   elif mutation=='symlink': db.unlink(); db.symlink_to(root/'elsewhere')
   elif mutation=='mode': db.chmod(0o644)
   else: db.unlink(); db.mkdir()
  return conn
 monkeypatch.setattr(sqlite3,'connect',mutate)
 with pytest.raises(IncompatibleError): tool._connect(root/'data.db',readonly=readonly)
 assert fired
 if writer: writer.close()
 assert len(list(Path('/dev/fd').iterdir()))<=baseline+1

def test_c2_readonly_wal_does_not_mutate_files(tmp_path:Path)->None:
 root=tmp_path/'f'; tool=_tool(root); assert tool.execute(FoundationRequest('init','c2-snapshot',UTC)).status=='initialized'; writer=tool._connect(root/'data.db'); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE c2_snapshot(v)'); writer.execute('INSERT INTO c2_snapshot VALUES(42)')
 try:
  files=[root/'data.db',root/'data.db-wal',root/'data.db-shm']
  before={p.name:(p.stat().st_ino,p.stat().st_mode&0o777,p.stat().st_mtime_ns,p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest()) for p in files if p.exists()}
  reader=tool._connect(root/'data.db',readonly=True)
  try: assert reader.execute('SELECT v FROM c2_snapshot').fetchone()[0]==42
  finally: reader.close()
  after={p.name:(p.stat().st_ino,p.stat().st_mode&0o777,p.stat().st_mtime_ns,p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest()) for p in files if p.exists()}
  assert before==after
 finally: writer.close()


def test_c2_readonly_wal_zero_write_and_fd_loop(tmp_path:Path)->None:
 baseline=len(list(Path('/dev/fd').iterdir()))
 for index in range(20):
  root=tmp_path/f'wal-snapshot-{index}'/'f'; root.parent.mkdir(); tool=_tool(root)
  assert tool.execute(FoundationRequest('init',f'c2-snapshot-loop-{index}',UTC)).status=='initialized'
  writer=tool._connect(root/'data.db'); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE c2_snapshot(v)'); writer.execute('INSERT INTO c2_snapshot VALUES(42)')
  try:
   files=[root/'data.db',root/'data.db-wal',root/'data.db-shm']
   before={p.name:(p.stat().st_ino,p.stat().st_mode&0o777,p.stat().st_mtime_ns,p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest()) for p in files if p.exists()}
   reader=tool._connect(root/'data.db',readonly=True)
   try: assert reader.execute('SELECT v FROM c2_snapshot').fetchone()[0]==42
   finally: reader.close()
   after={p.name:(p.stat().st_ino,p.stat().st_mode&0o777,p.stat().st_mtime_ns,p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest()) for p in files if p.exists()}
   assert before==after and not list(root.glob('.foundation-readonly-*'))
  finally: writer.close()
 assert len(list(Path('/dev/fd').iterdir()))<=baseline+1


class _DatabaseListCursor:
 def __init__(self,rows:object)->None: self.rows=rows
 def fetchall(self)->object: return self.rows


@pytest.mark.parametrize(
 'case,rows',[
  ('empty',[]),
  ('no_main',[(0,'aux','/tmp/aux.db')]),
  ('two_main',[(0,'main','/tmp/a.db'),(1,'main','/tmp/b.db')]),
  ('short_tuple',[(0,'main')]),
  ('relative_path',[(0,'main','relative.db')]),
  ('empty_path',[(0,'main','')]),
  ('wrong_absolute',[(0,'main','/tmp/wrong.db')]),
  ('attached_non_main',[(0,'main','/tmp/a.db'),(2,'aux','/tmp/aux.db')]),
 ],
)
def test_c2_database_list_malformed_rows_fail_closed_without_fd_leak(tmp_path:Path,monkeypatch:pytest.MonkeyPatch,case:str,rows:object)->None:
 """Every malformed metadata category is exercised twenty times on one safe DB."""
 root=tmp_path/'f'; tool=_tool(root); assert tool.execute(FoundationRequest('init',f'c2-list-{case}',UTC)).status=='initialized'
 original=foundation._PinnedConnection.execute; baseline=len(list(Path('/dev/fd').iterdir()))
 def execute(self,sql,*args,**kwargs):
  if sql=='PRAGMA database_list': return _DatabaseListCursor(rows)
  return original(self,sql,*args,**kwargs)
 monkeypatch.setattr(foundation._PinnedConnection,'execute',execute)
 for _ in range(20):
  with pytest.raises(IncompatibleError,match='sqlite_database_list_unsafe'): tool._connect(root/'data.db')
 assert len(list(Path('/dev/fd').iterdir()))<=baseline+1


def test_c2_database_list_execute_and_close_fault_preserves_primary_error_and_closes_fds(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 root=tmp_path/'f'; tool=_tool(root); assert tool.execute(FoundationRequest('init','c2-list-close',UTC)).status=='initialized'
 original_execute=foundation._PinnedConnection.execute; original_close=foundation._PinnedConnection.close; baseline=len(list(Path('/dev/fd').iterdir())); close_calls=0
 def execute(self,sql,*args,**kwargs):
  if sql=='PRAGMA database_list': raise sqlite3.OperationalError('database-list-fault')
  return original_execute(self,sql,*args,**kwargs)
 def close(self):
  nonlocal close_calls
  close_calls+=1
  original_close(self)
  raise OSError('close-fault')
 monkeypatch.setattr(foundation._PinnedConnection,'execute',execute)
 monkeypatch.setattr(foundation._PinnedConnection,'close',close)
 for _ in range(20):
  with pytest.raises(IncompatibleError,match='sqlite_database_list_unsafe'): tool._connect(root/'data.db')
 assert close_calls==20
 assert len(list(Path('/dev/fd').iterdir()))<=baseline+1


def test_c2_database_list_valid_main_rejects_non_tuple_rows(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 root=tmp_path/'f'; tool=_tool(root); assert tool.execute(FoundationRequest('init','c2-list-types',UTC)).status=='initialized'
 original=foundation._PinnedConnection.execute
 def execute(self,sql,*args,**kwargs):
  if sql=='PRAGMA database_list': return _DatabaseListCursor([{'seq':0,'name':'main','file':str(root/'data.db')}])
  return original(self,sql,*args,**kwargs)
 monkeypatch.setattr(foundation._PinnedConnection,'execute',execute)
 with pytest.raises(IncompatibleError,match='sqlite_database_list_unsafe'): tool._connect(root/'data.db')


def test_c2_custom_database_wal_snapshot_has_one_connect_and_dynamic_cleanup(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 root=tmp_path/'f'; tool=_custom_tool(root); assert tool.execute(FoundationRequest('init','c2-custom',UTC)).status=='initialized'; db=root/'custom.sqlite'
 writer=tool._connect(db); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE custom_probe(v)'); writer.execute('INSERT INTO custom_probe VALUES(9)')
 original=sqlite3.connect; calls=0
 def counted(target,*args,**kwargs):
  nonlocal calls
  if '.foundation-readonly-' in str(target): calls+=1
  return original(target,*args,**kwargs)
 monkeypatch.setattr(sqlite3,'connect',counted)
 try:
  reader=tool._connect(db,readonly=True)
  try: assert reader.execute('SELECT v FROM custom_probe').fetchone()[0]==9 and calls==1
  finally: reader.close()
  assert not list(root.glob('.foundation-readonly-*'))
 finally: writer.close()


def test_c2_snapshot_connect_failure_recovers_dynamic_snapshot(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 root=tmp_path/'f'; tool=_custom_tool(root); assert tool.execute(FoundationRequest('init','c2-connect-fail',UTC)).status=='initialized'; db=root/'custom.sqlite'
 writer=tool._connect(db); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE connect_fail(v)'); writer.execute('INSERT INTO connect_fail VALUES(1)'); original=sqlite3.connect; calls=0; baseline=len(list(Path('/dev/fd').iterdir()))
 def fail_snapshot(target,*args,**kwargs):
  nonlocal calls
  if '.foundation-readonly-' in str(target): calls+=1; raise sqlite3.OperationalError('snapshot-connect')
  return original(target,*args,**kwargs)
 monkeypatch.setattr(sqlite3,'connect',fail_snapshot)
 try:
  with pytest.raises(sqlite3.OperationalError,match='snapshot-connect'): tool._connect(db,readonly=True)
  assert calls==1 and not list(root.glob('.foundation-readonly-*'))
 finally: writer.close()
 assert len(list(Path('/dev/fd').iterdir()))<=baseline+1


def test_c2_snapshot_connect_failure_fd_loop_twenty_times(tmp_path:Path)->None:
 baseline=len(list(Path('/dev/fd').iterdir()))
 for index in range(20):
  root=tmp_path/f'connect-loop-{index}'/'f'; root.parent.mkdir(); tool=_custom_tool(root); db=root/'custom.sqlite'
  assert tool.execute(FoundationRequest('init',f'c2-connect-loop-{index}',UTC)).status=='initialized'
  writer=tool._connect(db); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE fail_loop(v)'); writer.execute('INSERT INTO fail_loop VALUES(1)')
  with pytest.MonkeyPatch.context() as patch:
   original=sqlite3.connect; calls=0
   def fail_snapshot(target,*args,**kwargs):
    nonlocal calls
    if '.foundation-readonly-' in str(target): calls+=1; raise sqlite3.OperationalError('snapshot-connect')
    return original(target,*args,**kwargs)
   patch.setattr(sqlite3,'connect',fail_snapshot)
   with pytest.raises(sqlite3.OperationalError,match='snapshot-connect'): tool._connect(db,readonly=True)
   assert calls==1 and not list(root.glob('.foundation-readonly-*'))
  writer.close()
 assert len(list(Path('/dev/fd').iterdir()))<=baseline+1


def test_c2_snapshot_close_fault_after_cleanup_does_not_leak_dynamic_snapshot(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 root=tmp_path/'f'; tool=_custom_tool(root); assert tool.execute(FoundationRequest('init','c2-close-fault',UTC)).status=='initialized'; db=root/'custom.sqlite'
 writer=tool._connect(db); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE close_fault(v)'); writer.execute('INSERT INTO close_fault VALUES(1)'); baseline=len(list(Path('/dev/fd').iterdir()))
 original=foundation._PinnedConnection.close; calls=0
 def close_fault(self):
  nonlocal calls
  calls+=1; original(self); raise OSError('close-fault')
 monkeypatch.setattr(foundation._PinnedConnection,'close',close_fault)
 try:
  reader=tool._connect(db,readonly=True)
  with pytest.raises(OSError,match='close-fault'): reader.close()
  assert calls==1 and not list(root.glob('.foundation-readonly-*'))
 finally:
  monkeypatch.setattr(foundation._PinnedConnection,'close',original)
  writer.close()
 assert len(list(Path('/dev/fd').iterdir()))<=baseline+1


def test_c2_snapshot_cleanup_child_swap_preserves_foreign_and_blocks(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 root=tmp_path/'f'; tool=_custom_tool(root); assert tool.execute(FoundationRequest('init','c2-cleanup-swap',UTC)).status=='initialized'; db=root/'custom.sqlite'
 writer=tool._connect(db); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE cleanup_swap(v)'); writer.execute('INSERT INTO cleanup_swap VALUES(1)')
 reader=tool._connect(db,readonly=True); snapshot=next(root.glob('.foundation-readonly-*')); original=os.rename; swapped=False
 def rename(src,dst,*args,**kwargs):
  nonlocal swapped
  source_fd=kwargs.get('src_dir_fd')
  if not swapped and src==db.name and str(dst).startswith('.foundation-snapshot-cleanup-') and source_fd is not None:
   swapped=True; foreign=snapshot/'foreign'; foreign.write_bytes(b'FOREIGN'); foreign.chmod(0o600); os.replace(foreign,snapshot/db.name)
  return original(src,dst,*args,**kwargs)
 monkeypatch.setattr(os,'rename',rename)
 try:
  with pytest.raises(OSError,match='foundation_snapshot_replaced'): reader.close()
  assert swapped and (snapshot/db.name).read_bytes()==b'FOREIGN'
  with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(db,readonly=True)
 finally: writer.close()


def test_c2_snapshot_unlink_window_preserves_foreign_child_and_blocks(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 """The final unlink is of a private claim, never the canonical child name."""
 root=tmp_path/'f'; tool=_custom_tool(root); assert tool.execute(FoundationRequest('init','c2-unlink-window',UTC)).status=='initialized'; db=root/'custom.sqlite'
 writer=tool._connect(db); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE unlink_window(v)'); writer.execute('INSERT INTO unlink_window VALUES(1)')
 reader=tool._connect(db,readonly=True); snapshot=next(root.glob('.foundation-readonly-*')); original=os.unlink; swapped=False
 def unlink(name,*args,**kwargs):
  nonlocal swapped
  if not swapped and str(name).startswith('.foundation-snapshot-cleanup-') and kwargs.get('dir_fd') is not None:
   swapped=True; foreign=snapshot/'foreign'; foreign.write_bytes(b'FOREIGN'); foreign.chmod(0o600); os.replace(foreign,snapshot/db.name)
  return original(name,*args,**kwargs)
 monkeypatch.setattr(os,'unlink',unlink)
 try:
  with pytest.raises(OSError,match='foundation_snapshot_unexpected_object'): reader.close()
  assert swapped and (snapshot/db.name).read_bytes()==b'FOREIGN'
  with pytest.raises(IncompatibleError,match='sqlite_create_cleanup_blocker'): tool._connect(db,readonly=True)
 finally: writer.close()


def test_c2_snapshot_same_size_wal_mutation_is_rejected(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 root=tmp_path/'f'; tool=_tool(root); assert tool.execute(FoundationRequest('init','c2-same-size',UTC)).status=='initialized'; db=root/'data.db'
 writer=tool._connect(db); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE mutate_wal(v)'); writer.execute('INSERT INTO mutate_wal VALUES(1)')
 original_open=os.open; original_read=os.read; wal_fd=-1; reads=0; mutated=False
 def opened(name,flags,*args,**kwargs):
  nonlocal wal_fd
  value=original_open(name,flags,*args,**kwargs)
  if name==db.name+'-wal' and not (flags&os.O_CREAT): wal_fd=value
  return value
 def read(fd,size):
  nonlocal reads,mutated
  if fd==wal_fd:
   reads+=1
   # strict-source pre-digest (two reads), copy (two reads), then
   # mutate immediately before the post-copy digest without changing size.
   if reads==5 and not mutated:
    mutated=True; raw=(root/(db.name+'-wal')).read_bytes(); (root/(db.name+'-wal')).write_bytes(bytes((byte ^ 0xFF for byte in raw)))
  return original_read(fd,size)
 monkeypatch.setattr(os,'open',opened); monkeypatch.setattr(os,'read',read)
 try:
  with pytest.raises(IncompatibleError,match='sqlite_wal_state_unsafe'): tool._connect(db,readonly=True)
  assert mutated and not list(root.glob('.foundation-readonly-*'))
 finally: writer.close()


def test_c2_snapshot_malformed_wal_fails_without_snapshot_residue(tmp_path:Path)->None:
 root=tmp_path/'f'; tool=_custom_tool(root); assert tool.execute(FoundationRequest('init','c2-malformed-wal',UTC)).status=='initialized'; db=root/'custom.sqlite'
 writer=tool._connect(db); writer.execute('PRAGMA wal_autocheckpoint=0'); writer.execute('CREATE TABLE malformed_wal(v)'); writer.execute('INSERT INTO malformed_wal VALUES(1)')
 try:
  wal=root/(db.name+'-wal'); raw=wal.read_bytes(); wal.write_bytes(b'X'*len(raw))
  with pytest.raises(IncompatibleError,match='sqlite_wal_state_unsafe'): tool._connect(db,readonly=True)
  assert not list(root.glob('.foundation-readonly-*'))
 finally: writer.close()
