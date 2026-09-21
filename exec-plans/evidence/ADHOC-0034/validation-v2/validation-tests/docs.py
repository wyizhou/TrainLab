from pathlib import Path
import re,json,unicodedata,urllib.parse,sys
R=Path(__file__).resolve().parent.parent
M=json.loads((R/'manifest.json').read_text())
checks=[];links=[]
def check(n,ok,d=None): checks.append({'name':n,'pass':bool(ok),'detail':d})
def slug(s):
 s=re.sub(r'<[^>]*>','',s).lower();s=re.sub(r'[^\w\- ]','',s,flags=re.UNICODE);return s.replace(' ','-')
def anchors(p):
 result=set();counts={}
 for line in p.read_text().splitlines():
  m=re.match(r'^#{1,6}\s+(.+?)(?:\s+#+)?$',line)
  if m:
   s=slug(m[1]);n=counts.get(s,0);counts[s]=n+1;result.add(s if n==0 else s+'-'+str(n))
 return result
for c in ['C34','Cuse']:
 root=R/c
 docs=set(M['harness'])|{'PLAN.md','MEMORY.md','references/README.md','exec-plans/active/ADHOC-0034-agentsmd-parallel.md','exec-plans/evidence/ADHOC-0034/handoff-v2.md'}
 if c=='Cuse':docs.add('exec-plans/active/ADHOC-0033-ai-coach.md')
 for name in sorted(docs):
  p=root/name;text=p.read_text()
  for m in re.finditer(r'\[[^\]\n]*\]\(([^\s)]+)\)',text):
   url=urllib.parse.unquote(m[1]);parts=urllib.parse.urlsplit(url)
   if parts.scheme or url.startswith('//'):continue
   dest=(p.parent/parts.path).resolve() if parts.path else p
   exists=dest.exists() and dest.is_relative_to(root)
   # No archived reports/scripts are read for conclusions or link bodies.
   fragok=True;fragmethod='none'
   if exists and parts.fragment:
    if 'evidence' in dest.parts and dest.name not in {'requirements.md','handoff-v2.md'}:fragmethod='not-read-evidence-anchor'
    else:fragok=parts.fragment in anchors(dest);fragmethod='heading slug'
   prior=R/'inputs'/('baseline-C34' if c=='C34' else 'history-baseline-Cuse')/name
   if not prior.exists():prior=R/'inputs/before'/name
   inherited=prior.exists() and m[0] in prior.read_text()
   links.append({'source':c+'/'+name,'line':text[:m.start()].count('\n')+1,'url':url,'exists_inside_combo':exists,'anchor_ok':fragok,'anchor_method':fragmethod,'inherited':inherited})
 bad=[x for x in links if x['source'].startswith(c+'/') and not(x['exists_inside_combo'] and x['anchor_ok'])]
 check(c+'_links_no_new_breaks',not any(not x['inherited'] for x in bad),bad)
 normpaths=list(M['harness'])
 check(c+'_generic_AI_relative_norms',all(not re.search(r'/(?:Users|home|private|var|opt)/|\b(?:OpenAI|Anthropic|Claude|Codex|ChatGPT|Gemini)\b',(root/p).read_text(),re.I) for p in normpaths))
 t=(root/'exec-plans/template.md').read_text().split('## 流水线与并行开发安排')[1].split('## 当前检查点')[0]
 check(c+'_nine_parallel_fields',len(re.findall(r'^- ',t,re.M))==9)
 t=(root/'exec-plans/active/ADHOC-0034-agentsmd-parallel.md').read_text().split('## 流水线与并行开发安排')[1].split('## 当前检查点')[0]
 check(c+'_plan_nine_parallel_fields',len(re.findall(r'^- ',t,re.M))==9)
 for role in ['planner','developer','validator']:
  text=(root/'subagent-templates'/f'{role}.md').read_text()
  check(c+'_'+role+'_fields',all(s in text for s in ['每目录最多一名','共享文件、接口及重要数据规则的修改归属','固定版本与交接条件','实际组合版本及相关依赖','停止条件与报告对象','输入与预期输出']))
readme=(R/'C34/README.md').read_text();check('complete_MIT',all(s in readme for s in ['Copyright (c) 2026 wyizhou','The above copyright notice and this permission notice','SOFTWARE.']))
skill=(R/'C34/skills/web-browser-acceptance/SKILL.md').read_text();check('skill_selfcontained_and_no_browser_for_docs','本技能仅由本 Markdown 文档组成' in skill and '仅涉及说明文档、且不影响网页行为的修改：无需启动浏览器验收' in skill)
scenarios=[
 ('N01','开发A时B规划输入已齐，A尚未合并','允许先规划B','不因无关的后续实现或合并阻塞规划'),
 ('N02','A冻结实际差异/依赖，B已主审且写入资源齐','允许验证A并开发B','A 开发结束并固定受审内容及相关依赖后'),
 ('N03','独立功能在独立目录分支，接口及测试资源就绪','允许多个Developer','可由多个 Developer 在各自独立工作目录和分支并行开发'),
 ('E01','同目录两人分文件写','拒绝','即使修改不同文件也不能在同一目录安排多个 Developer'),
 ('E02','独立目录但共用数据库/账号/端口冲突','暂停或串行受影响项','独立目录不代表数据库、账号、端口等测试资源已隔离'),
 ('E03','B未审核就开发','拒绝','启动开发前必须完成规划审核'),
 ('E04','规划B所需接口未确定','等待必要输入','不把尚未就绪的必要接口当作已确定'),
 ('E05','共享文件在两分支各自修改','拒绝；唯一归属','不能在各分支重复修改同一共享项'),
 ('E06','只提供分支名或仍可写原目录作冻结','拒绝','不能只写分支名或指向同一可变目录'),
 ('E07','各单体通过或无文本冲突即交付组合','拒绝；组合独立及主验收','各功能分别通过或没有文本冲突都不能代替最终组合版本通过'),
 ('B01','共享责任方修改后消费方继续旧确认','必须交接并重核','依赖方重新核对输入就绪情况'),
 ('B02','冻结后依赖变动仍沿旧证据','停止受影响检查并重固定/全新复验','旧证据不得用于变化后的版本'),
 ('B03','A失败但独立B条件满足','仅停受影响链；不绕停止线','其他真正独立且条件满足的任务可继续，不以此绕过累计失败阈值'),
 ('B04','两种实质修法仍失败或三轮不收敛','停并由真实用户决定','两种实质不同修法仍失败，或连续三轮修复与验证不收敛时暂停'),
 ('B05','仅补写真实结果/状态','主核精确差异；规则语义变化仍新验','仅补写真实结果和状态时，由主 Agent 检查差异即可'),
]
A=(R/'C34/AGENTS.md').read_text()
scenario_results=[]
for ident,scene,expected,clause in scenarios:
 ok=clause in A
 line=A[:A.index(clause)].count('\n')+1 if ok else None
 scenario_results.append({'id':ident,'input':scene,'expected':expected,'actual':'规则明确支持预期' if ok else '缺少条款','AGENTS_line':line,'method':'独立人工逐场景判读；非调度器运行','pass':ok})
check('independent_semantic_scenarios15',all(x['pass'] for x in scenario_results))
report={'checks':checks,'links':links,'scenarios':scenario_results,'link_total':len(links),'broken': [x for x in links if not(x['exists_inside_combo'] and x['anchor_ok'])],'anchor_unchecked':[x for x in links if x['anchor_method']=='not-read-evidence-anchor']}
(R/'validation-evidence/docs.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'checks':len(checks),'failed':[x for x in checks if not x['pass']],'link_total':len(links),'broken':report['broken'],'anchor_unchecked':report['anchor_unchecked']},ensure_ascii=False,indent=2));sys.exit(any(not x['pass'] for x in checks))
