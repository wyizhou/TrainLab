from pathlib import Path
import datetime,hashlib,json,os,shutil,subprocess,tempfile
R=Path.cwd(); E=R/'exec-plans/evidence/ADHOC-0034'; J=lambda p:json.loads(Path(p).read_text()); S=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest(); cfg=J(E/'worktree.json'); W=Path(cfg['worktree']); B=J(E/'baseline.json'); DB=J(E/'developer-baseline.json'); H=DB['allowed_changes']
assert all(S(R/p)==h for p,h in B['source_files'].items())
assert subprocess.check_output(['git','diff','--','source'])==(E/'source-before.diff').read_bytes()
old=J(E/'protected-old-evidence.json')
for p,v in old.items():
 assert (str((R/p).readlink())==v['symlink']) if 'symlink' in v else S(R/p)==v['sha256'],p
base=Path(tempfile.mkdtemp(prefix='trainlab-adhoc0034-review-')); inputs=base/'inputs';inputs.mkdir(); cu=base/'Cuse';cu.mkdir();c34=base/'C34';c34.mkdir()
def cp(src,dst):
 dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
def public_paths(root):
 paths=set(subprocess.check_output(['git','-C',str(root),'ls-files','--cached','--others','--exclude-standard','-z'],text=True).split('\0'))-{''}
 return sorted(p for p in paths if p in ['.gitignore','AGENTS.md','README.md','PLAN.md','MEMORY.md'] or p.startswith(('source/','references/','skills/','subagent-templates/','exec-plans/')))
rpaths=set(public_paths(R))|set(B['source_files']); excluded={}
for p in sorted(rpaths):
 f=R/p
 if f.is_symlink():excluded[p]={'symlink':str(f.readlink()),'reason':'Historical execution environment, not a dependency of this Markdown upgrade; original remains protected.'};continue
 if f.exists():cp(f,cu/p)
prelanding={p:(S(R/p) if (R/p).is_file() else None) for p in H+['PLAN.md','MEMORY.md','exec-plans/active/ADHOC-0033-ai-coach.md']}
for p in ['PLAN.md','MEMORY.md','exec-plans/active/ADHOC-0033-ai-coach.md']:cp(R/p,inputs/'baseline-Cuse'/p)
for p in ['PLAN.md','MEMORY.md']:
 q=inputs/'baseline-C34'/p;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(subprocess.check_output(['git','-C',str(W),'show',cfg['head']+':'+p]))
for p in H:cp(W/p,cu/p)
for p in ['developer-intake.md','developer-dispatch.json','upstream.json']:cp(E/p,W/'exec-plans/evidence/ADHOC-0034'/p)
cp(R/'exec-plans/active/ADHOC-0034-agentsmd-parallel.md',W/'exec-plans/active/ADHOC-0034-agentsmd-parallel.md')
for root in [cu]:
 p=root/'MEMORY.md';text=p.read_text();oldrow=next(x for x in text.splitlines() if x.startswith('| 当前脚手架 |'))
 newrow='| 当前脚手架 | 采用agentsmd固定提交37520a5132bb5f84064e04f18d7a4467ebdc9116；AGENTS、README、角色/执行计划模板与网页验收技能采用上游原字节，索引保留项目边界。允许符合隔离和就绪条件的流水线/跨功能并行，每目录仍最多一名Developer；共享项唯一修改、固定交接，最终组合独立及主验收不可省略。业务计划/记忆不由空模板替换，升级不恢复暂停业务、不改调度器或全局配置。 | 用户最新版升级要求，2026-09-20；[本轮来源与范围](exec-plans/evidence/ADHOC-0034/requirements.md)。此前768a3143迁移来源保留：[原迁移](exec-plans/completed/ADHOC-0029-agentsmd-upgrade.md) |'
 assert text.count(oldrow)==1;p.write_text(text.replace(oldrow,newrow))
p=cu/'exec-plans/active/ADHOC-0033-ai-coach.md';text=p.read_text();addition='## 脚手架升级期间的隔离安排（2026-09-20）\n\n- 本功能继续暂停，当前没有Developer；已审核P02/A1方案不等于恢复授权，单轮修复尚未开始。恢复范围由用户另行明确，旧任务、问题编号、失败计数和证据保留。\n- 0034在独立目录/分支更新唯一Harness版本，本功能只消费经过两组合独立及主验收的同版文件；不各自修改共享规则。PLAN/MEMORY/执行计划由主维护，产品及旧证据不写入。\n- 当前只需固定已有公开材料用于脚手架兼容核对；不要求后续业务接口提前就绪，不运行数据库、账号、端口、真实请求或浏览器。新并行规则不改变原暂停条件。恢复开发前重新核当前输入、固定代码/依赖、目录/分支、测试资源和共享交接，再按原失败停止线及新规则派发。\n- 主Agent负责0034独立PR组合与本工作区含未提交产品的组合核对；本次文档验收不等于0033产品验收，不提交其产品差异。\n\n'
assert addition not in text;text=text.replace('\n## ', '\n'+addition+'## ',1);p.write_text(text)
for p in public_paths(W):
 if (W/p).is_file():cp(W/p,c34/p)
for name in ['requirements.md','upstream.json','baseline.json','protected-old-evidence.json','developer-baseline.json']:cp(E/name,inputs/name)
shutil.copytree(E/'upstream',inputs/'upstream')
planner=(E/'planner.md').read_text().split('## 实际检查及未验项')[0];(inputs/'approved-decomposition.md').write_text(planner.replace('本方案待主Agent审核；以下是实施安排，不表示已经升级或验收通过。','本方案的任务、职责及两组合安排已由主Agent审核。以下为批准拆解，不是验证结论。'))
for name,root in [('C34',W),('Cuse',R)]:
 (inputs/(name+'-git-status.txt')).write_bytes(subprocess.check_output(['git','-C',str(root),'status','--short']))
 (inputs/(name+'-git-diff.patch')).write_bytes(subprocess.check_output(['git','-C',str(root),'diff']))
meta={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'review_root':str(base),'combinations':{'C34':{'base':cfg['head'],'branch':cfg['branch']},'Cuse':{'base':B['head'],'branch':B['branch']}},'harness_paths':H,'prelanding':prelanding,'excluded_legacy_environment_links':excluded,'source_protected':len(B['source_files']),'old_evidence_protected':len(old),'note':'Two physical public combinations, not Git checkouts. No private states/.pi/global data. Three old interpreter symlinks recorded but not copied/followed; not current review dependencies. Final manifest follows after current coordination checkpoint.'}
(E/'combination-location.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n');(inputs/'combination-location.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
for root in [W,c34,cu]:cp(E/'combination-location.json',root/'exec-plans/evidence/ADHOC-0034/combination-location.json')
print(json.dumps({'review_root':str(base),'C34_files':len(list(c34.rglob('*'))),'Cuse_entries':len(list(cu.rglob('*'))),'excluded_symlinks':len(excluded),'source_unchanged':179,'old_evidence_unchanged':len(old)},ensure_ascii=False,indent=2))
