"""Independent employee identities, isolated context, collaboration and CEO desk."""
from __future__ import annotations
import argparse, datetime as dt, json, re
from pathlib import Path
import office

STAFF = [
 ('baek_chief','baek','업무실장','CEO','인간 CEO의 마케팅·사무 업무를 정리하고 우선순위·담당자·완료 기준을 제안한다.'),
 ('baek_marketing','baek','마케팅 전략','CMO','고객·채널·프로모션 가설과 실행 가능한 캠페인 초안을 만든다. 확정되지 않은 제품·가격·효능을 만들지 않는다.'),
 ('baek_content','baek','콘텐츠 담당','CSO','상품 설명·광고 소재·SNS·이메일 초안을 작성한다. 초안을 실제 게시하거나 발송하지 않는다.'),
 ('baek_orders','baek','주문 정리','CTO','주문지 엑셀·CSV의 열과 행을 보존하고 수량·누락·중복 의심을 정리한다. 고객정보는 로컬 전용 처리기로 다룬다.'),
 ('baek_admin','baek','사무 지원','CTO','문서 정리·회의 준비·목록·일정 초안과 반복 업무 절차를 만든다.'),
 ('baek_review','baek','품질 검수','CLO','다른 직원 결과의 숫자·근거·문구·개인정보 노출과 누락을 별도 세션에서 검수한다.'),
 ('startup_chief','startup','창업 실장','CEO','직원들의 독립 의견을 모아 쟁점·다음 행동·CEO 결정 사항을 정한다. 인간 CEO를 대신해 사업 결정을 확정하지 않는다.'),
 ('startup_research','startup','시장 조사','CMO','실제 공개 원문을 조사하고 고객 문제·경쟁 대안·시장 가설을 출처와 날짜로 정리한다.'),
 ('startup_strategy','startup','사업 전략','CSO','사업 후보와 수익 구조를 독립 검토하고 반증 조건·가장 작은 실험을 제안한다.'),
 ('startup_product','startup','제품 실험','CTO','실험 설계·인터뷰 질문·MVP 요구사항·검증 기준을 작성한다.'),
 ('startup_finance','startup','재무·위험','CFO','비용·가격·마진 가정을 계산하고 불확실성과 법무 확인 질문을 정리한다. 지출이나 법적 확정 판단을 하지 않는다.'),
 ('startup_review','startup','독립 검수','CLO','사업 가설과 실행안을 반대 관점으로 검토하고 근거 오류·산식·완료 기준을 검사한다.')
]
PROJECTS={'baek':'백년화편 업무 지원','startup':'신규 스타트업 사무실'}
DEFAULT_MISSIONS={
 'baek':'인간 CEO의 마케팅 및 사무 잡무를 돕는다. 주문지 엑셀 정리, 콘텐츠 초안, 업무 정리를 우선한다. 실제 회사 내부 자료는 제공되기 전까지 추정하지 않는다.',
 'startup':'인간 CEO와 함께 신규 스타트업을 창립한다. 직원들이 독립적으로 후보·문제·근거를 고민하고 공개 조사·문서·실험 설계를 수행한다. 사업 선택과 외부 약속은 인간 CEO가 결정한다.'}

def init_schema():
    with office.db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS employees(id TEXT PRIMARY KEY,project TEXT NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL,responsibility TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS office_missions(project TEXT PRIMARY KEY,mission TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY,project TEXT NOT NULL,goal TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS employee_notes(id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,task_id TEXT NOT NULL,summary TEXT NOT NULL,observed TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS handoffs(id TEXT PRIMARY KEY,project TEXT NOT NULL,from_agent TEXT NOT NULL,to_agent TEXT NOT NULL,task_id TEXT NOT NULL,body TEXT NOT NULL,observed TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ceo_decisions(id TEXT PRIMARY KEY,project TEXT NOT NULL,campaign_id TEXT,decision TEXT NOT NULL,reason TEXT NOT NULL,source TEXT NOT NULL,observed TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS automation_claims(claim TEXT PRIMARY KEY,project TEXT NOT NULL,observed TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS processed_actions(task_id TEXT PRIMARY KEY,observed TEXT NOT NULL);
        ''')
        for sid,p,name,role,resp in STAFF:
            c.execute('INSERT OR IGNORE INTO employees(id,project,name,role,responsibility) VALUES (?,?,?,?,?)',(sid,p,name,role,resp))
        for p,mission in DEFAULT_MISSIONS.items(): c.execute('INSERT OR IGNORE INTO office_missions VALUES (?,?,?)',(p,mission,office.now()))
    for p in PROJECTS:
        (office.ROOT/'inbox'/p).mkdir(parents=True,exist_ok=True)

def employee(agent_id):
    with office.db() as c: r=c.execute('SELECT * FROM employees WHERE id=? AND enabled=1',(agent_id,)).fetchone()
    if not r: raise ValueError('Unknown or disabled employee')
    return dict(r)

def reviewer_for(project): return project+'_review'

def assign(agent_id,title,brief,kind='document',dependencies=None,campaign=None,important=True,dedupe=None):
    agent=employee(agent_id)
    if not title.strip() or not brief.strip(): raise ValueError('Title and task input are required')
    if campaign:
        with office.db() as c: row=c.execute('SELECT project,status FROM campaigns WHERE id=?',(campaign,)).fetchone()
        if not row or row['project']!=agent['project'] or row['status']=='STOPPED': raise ValueError('Invalid office campaign')
    if kind not in {'document','public_research','synthesis'}: raise ValueError('Unsupported execution kind')
    if kind=='public_research' and agent['project']=='baek':
        raise ValueError('Baek private office research is disabled until a public brief is explicitly scoped')
    return office.add(title,brief,role=agent['role'],important=important,project=agent['project'],
      owner_agent=agent_id,dependencies=dependencies,campaign_id=campaign,task_kind=kind,dedupe_key=dedupe)

def employee_context(task):
    agent=employee(task['owner_agent'])
    if agent['project']!=task['project']: raise ValueError('Cross-office employee assignment')
    with office.db() as c:
        mission=c.execute('SELECT mission FROM office_missions WHERE project=?',(agent['project'],)).fetchone()['mission']
        notes=[dict(r) for r in c.execute('SELECT task_id,summary,observed FROM employee_notes WHERE agent_id=? ORDER BY observed DESC LIMIT 5',(agent['id'],))]
        decisions=[dict(r) for r in c.execute('SELECT decision,reason,observed FROM ceo_decisions WHERE project=? ORDER BY observed DESC LIMIT 5',(agent['project'],))]
        material=[]; deps=json.loads(task['dependencies'])
        if agent['id'].endswith('_chief') and not deps:
            deps=[r['task_id'] for r in c.execute('SELECT task_id FROM handoffs WHERE to_agent=? AND project=? ORDER BY observed DESC LIMIT 6',(agent['id'],agent['project']))]
        for dep in deps:
            prior=c.execute('SELECT project,status,title FROM tasks WHERE id=?',(dep,)).fetchone()
            if not prior or prior['project']!=agent['project']: raise ValueError('Cross-office handoff denied')
            if prior['status']!='DONE': continue
            a=c.execute("SELECT a.* FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.task_id=? AND a.verified=1 AND r.purpose='execute' ORDER BY r.started DESC LIMIT 1",(dep,)).fetchone()
            if a:
                path=(office.ROOT/a['path']).resolve()
                if not path.is_relative_to((office.ROOT/'runs').resolve()) or office.digest(path.read_bytes())!=a['sha256']: raise ValueError('Handoff artifact integrity failure')
                text=path.read_text(encoding='utf-8')
                result=json.loads(path.with_name('result.json').read_text(encoding='utf-8'))
                audit=result.get('web_activity',{})
                trace=path.with_name('stdout.jsonl')
                if not audit and trace.exists():
                    try:
                        final=json.loads(trace.read_text(encoding='utf-8'))
                        audit={'reported_search_requests':sum(m.get('webSearchRequests',0) for m in final.get('modelUsage',{}).values())}
                    except ValueError: pass
                material.append({'task':dep,'title':prior['title'],'artifact_sha256':a['sha256'],'recorded_web_activity':audit,'result':text[:7000]})
    return '\n'.join(['직원 ID: '+agent['id'],'직원 직책: '+agent['name'],'책임: '+agent['responsibility'],
      '소속 사무실: '+PROJECTS[agent['project']],'인간 CEO 지침: '+mission,
      '본인 업무 기억: '+json.dumps(notes,ensure_ascii=False),'인간 CEO 결정 기록: '+json.dumps(decisions,ensure_ascii=False),
      '명시적으로 전달받은 동료 산출물: '+json.dumps(material,ensure_ascii=False),
      '이번 호출은 본인만의 독립 세션이다. 동료를 연기하거나 동료가 일했다고 꾸미지 않는다. 독립 초안에서는 동료 초안을 전달받지 않는다. 기록된 인간 결정을 새 승인으로 확대하지 않는다.'])

def remember_result(task,result):
    with office.db() as c:
        c.execute('INSERT INTO employee_notes VALUES (?,?,?,?,?)',(office.uid(),task['owner_agent'],task['id'],result['text'][:1800],office.now()))
        chief=task['project']+'_chief'
        c.execute('INSERT INTO handoffs VALUES (?,?,?,?,?,?,?)',(office.uid(),task['project'],task['owner_agent'],chief,task['id'],task['title']+' 결과 제출',office.now()))

def create_campaign(project,goal):
    if project not in PROJECTS or not goal.strip(): raise ValueError('Office and goal are required')
    cid=office.uid()[:12]
    selected=(['baek_marketing','baek_admin','baek_content'] if project=='baek' else ['startup_research','startup_strategy','startup_product'])
    ids=[]; specs=[]
    for aid in selected:
        a=employee(aid)
        kind='public_research' if aid=='startup_research' else 'document'
        tid=office.uid()[:12]; ids.append(tid)
        specs.append((tid,aid,a['name']+' 독립 검토',goal+'\n본인 책임 관점에서 독립 초안을 800자 내외로 작성한다. 실제 수행한 작업과 제안만 한 작업을 구분하고 완료 기준을 넣는다.',kind,[],False))
    synthesis=office.uid()[:12]
    synthesis_prompt=goal+'\n동료들의 명시적 산출물을 읽고 합의·차이·근거 수준·권고·다음 행동을 정리한다. '
    synthesis_prompt+=(
        '실제 인간 결정 없이 사업 선택·지출·게시를 확정하지 않는다. 문서 마지막에 다음 내부 실행 최대 2개를 아래 형식으로 넣는다. '
        '이는 실행 제안이며 인간 승인을 위조할 수 없다. 후보 업무는 소속 직원에게만 배정한다. '
        '```office-actions\n{"actions":[{"agent_id":"소속 직원 ID","title":"구체적 업무","brief":"입력과 완료기준","kind":"document"}]}\n```\n'
        '가능한 직원: '+','.join(a[0] for a in STAFF if a[1]==project and not a[0].endswith('_review')))
    specs.append((synthesis,project+'_chief','인간 CEO 의사결정 보고',synthesis_prompt,'synthesis',ids,True))
    with office.lock(),office.db() as c:
        c.execute('INSERT INTO campaigns VALUES (?,?,?,?,?)',(cid,project,goal,'ACTIVE',office.now()))
        for tid,aid,title,brief,kind,deps,important in specs:
            role=next(a[3] for a in STAFF if a[0]==aid)
            c.execute('INSERT INTO tasks(id,project,title,prompt,role,status,criteria,dependencies,important,created,updated,owner_agent,campaign_id,task_kind,dedupe_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (tid,project,title,brief,role,'READY',json.dumps(['가정','근거','미확인','실험','완료 기준']),json.dumps(deps),int(important),office.now(),office.now(),aid,cid,kind,cid+':'+aid))
    return {'campaign_id':cid,'drafts':ids,'synthesis':synthesis}

def parse_actions(text,project):
    match=re.search(r'```office-actions\s*(\{.*?\})\s*```',text,re.S)
    if not match: return []
    data=json.loads(match.group(1)); actions=data.get('actions')
    if not isinstance(actions,list) or len(actions)>2: raise ValueError('At most two follow-up actions')
    valid=[]
    for a in actions:
        if not isinstance(a,dict) or set(a)!={'agent_id','title','brief','kind'}: raise ValueError('Invalid action schema')
        e=employee(a['agent_id'])
        if e['project']!=project or a['kind']!='document': raise ValueError('Only same-office internal document work is auto-assigned')
        if any(not isinstance(a[k],str) or not 1<=len(a[k])<=4000 for k in ['title','brief']): raise ValueError('Invalid action content')
        valid.append(a)
    return valid

def process_followups():
    """One bounded generation per synthesis; never recursively generates external actions."""
    with office.lock(), office.db() as c:
        for t in c.execute("SELECT * FROM tasks WHERE status='DONE' AND task_kind='synthesis' AND id NOT IN (SELECT task_id FROM processed_actions)").fetchall():
            if t['campaign_id']:
                campaign=c.execute('SELECT status FROM campaigns WHERE id=?',(t['campaign_id'],)).fetchone()
                if campaign and campaign['status']=='STOPPED': continue
            a=c.execute("SELECT a.path,a.sha256 FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.task_id=? AND a.verified=1 AND r.purpose='execute' ORDER BY r.started DESC LIMIT 1",(t['id'],)).fetchone()
            if not a: continue
            try:
                path=(office.ROOT/a['path']).resolve()
                if not path.is_relative_to((office.ROOT/'runs').resolve()) or office.digest(path.read_bytes())!=a['sha256']: raise ValueError('Follow-up artifact integrity failure')
                actions=parse_actions(path.read_text(encoding='utf-8'),t['project'])
            except (ValueError,KeyError,TypeError) as err:
                actions=[]; office.event(c,t['id'],'FOLLOWUP_REJECTED',str(err))
            # This connection owns the transaction; insert all child tasks atomically.
            for index,action in enumerate(actions):
                aid=action['agent_id']; tid=office.uid()[:12]; agent=employee(aid)
                c.execute('INSERT OR IGNORE INTO tasks(id,project,title,prompt,role,status,criteria,dependencies,important,created,updated,owner_agent,campaign_id,task_kind,dedupe_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (tid,t['project'],action['title'],action['brief'],agent['role'],'READY',json.dumps(['가정','근거','미확인','실험','완료 기준']),json.dumps([t['id']]),1,office.now(),office.now(),aid,t['campaign_id'],'document',t['id']+':followup:'+str(index)))
            c.execute('INSERT INTO processed_actions VALUES (?,?)',(t['id'],office.now()))
            c.execute('UPDATE campaigns SET status=? WHERE id=?',('WAITING_CEO',t['campaign_id']))

def ceo_decide(project,decision,reason,campaign=None):
    if project not in PROJECTS or decision not in {'SCALE','ITERATE','SIMPLIFY','KILL','PRIORITY','DIRECTION'}: raise ValueError('Invalid CEO decision')
    if not reason.strip(): raise ValueError('Decision reason required')
    with office.lock(), office.db() as c:
        if campaign:
            row=c.execute('SELECT project FROM campaigns WHERE id=?',(campaign,)).fetchone()
            if not row or row['project']!=project: raise ValueError('Cross-office campaign')
        decision_id=office.uid()
        c.execute('INSERT INTO ceo_decisions VALUES (?,?,?,?,?,?,?)',(decision_id,project,campaign,decision,reason,'LOCAL_CEO_DESK',office.now()))
        if campaign and decision=='KILL':
            c.execute("UPDATE campaigns SET status='STOPPED' WHERE id=?",(campaign,))
            for t in c.execute("SELECT id FROM tasks WHERE campaign_id=? AND status IN ('READY','PROPOSED','REVIEW','WAITING_EXTERNAL')",(campaign,)).fetchall(): office.state(c,t['id'],'CANCELLED','Human CEO stopped campaign')
        elif decision!='KILL':
            # Turn the recorded instruction into internal planning work, never an external authorization.
            staff=','.join(a[0] for a in STAFF if a[1]==project and not a[0].endswith('_review'))
            brief='인간 CEO 지침을 반영해 다음 내부 업무를 정리한다. 지침: '+reason+'\n사업 방향을 외부 행동 승인으로 확대하지 않는다. '
            brief+='최대 2개 새 문서 업무를 ```office-actions\n{"actions":[{"agent_id":"담당 ID","title":"업무","brief":"입력과 완료 기준","kind":"document"}]}\n``` 형식으로 제안한다. 없으면 빈 배열. 담당: '+staff
            c.execute('INSERT INTO tasks(id,project,title,prompt,role,status,criteria,dependencies,important,created,updated,owner_agent,campaign_id,task_kind,dedupe_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (office.uid()[:12],project,'인간 CEO 지침 반영',brief,'CEO','READY',json.dumps(['가정','근거','미확인','실험','완료 기준']),'[]',1,office.now(),office.now(),project+'_chief',campaign,'synthesis','decision:'+decision_id))
        office.event(c,None,'CEO_DECISION',project+': '+decision)

def ready_tasks(project=None):
    with office.db() as c:
        rows=c.execute("SELECT * FROM tasks WHERE status IN ('READY','WAITING_EXTERNAL') AND owner_agent IS NOT NULL ORDER BY created").fetchall()
        ready=[]
        for t in rows:
            if project and t['project']!=project: continue
            if t['campaign_id']:
                camp=c.execute('SELECT status FROM campaigns WHERE id=?',(t['campaign_id'],)).fetchone()
                if camp and camp['status']=='STOPPED': continue
            deps=json.loads(t['dependencies'])
            if all(c.execute('SELECT status FROM tasks WHERE id=?',(dep,)).fetchone()['status']=='DONE' for dep in deps):
                if t['status']=='READY': ready.append(dict(t))
                # Only dependency waiting is promoted; never retry an interrupted run.
                elif deps and not c.execute('SELECT 1 FROM runs WHERE task_id=?',(t['id'],)).fetchone():
                    office.state(c,t['id'],'READY','Dependencies completed'); ready.append(dict(t))
        return ready

def run_queue(limit=4,project=None):
    if not isinstance(limit,int) or not 1<=limit<=12: raise ValueError('Run limit must be 1 to 12 tasks')
    outcomes=[]; last_project=None
    for _ in range(limit):
        if (office.ROOT/'data/STOP').exists(): break
        with office.db() as c:
            if c.execute("SELECT 1 FROM tasks WHERE status IN ('WAITING_QUOTA','NEEDS_LOGIN') LIMIT 1").fetchone(): break
        rows=ready_tasks(project)
        if not rows: break
        task=next((t for t in rows if t['project']!=last_project),rows[0]); last_project=task['project']
        status=office.run_task(task['id']); outcomes.append({'task':task['id'],'status':status})
        if status in {'WAITING_QUOTA','NEEDS_LOGIN','WAITING_EXTERNAL','BLOCKED'}: break
        # Correct internal document drafts at most twice using saved review findings.
        if status=='REVIEW' and task['revisions']<office.config()['max_revision_rounds']:
            office.retry(task['id'])
        process_followups()
    return outcomes

def daily():
    if not office.config().get('automatic_execution'): return 'DISABLED'
    day=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    with office.lock(),office.db() as c:
        if (office.ROOT/'data/STOP').exists(): return 'PAUSED'
        key='team:'+day
        if c.execute('SELECT 1 FROM automation_claims WHERE claim=?',(key,)).fetchone(): return 'ALREADY_CLAIMED'
        c.execute('INSERT INTO automation_claims VALUES (?,?,?)',(key,'both',office.now()))
    # Persistent goals: plan again only when previous work has actually finished.
    for project in PROJECTS:
        with office.db() as c:
            live=c.execute("SELECT 1 FROM tasks WHERE project=? AND owner_agent IS NOT NULL AND status NOT IN ('DONE','CANCELLED')",(project,)).fetchone()
            mission=c.execute('SELECT mission FROM office_missions WHERE project=?',(project,)).fetchone()['mission']
        if not live:
            staff=','.join(a[0] for a in STAFF if a[1]==project and not a[0].endswith('_review'))
            assign(project+'_chief',day+' 업무 점검',mission+'\n이전 결과와 인간 CEO의 지침을 검토하고 오늘의 우선순위, 미확인, 실험, 완료 기준을 제안한다. 불필요한 반복 자료 작성을 피한다. '
              '실제로 새로 필요한 내부 문서 작업만 최대 2개를 마지막에 작성한다. 없으면 빈 actions 배열. '
              '```office-actions\n{"actions":[{"agent_id":"담당 ID","title":"새로운 업무","brief":"입력과 완료 기준","kind":"document"}]}\n```\n담당 ID: '+staff,
              kind='synthesis',important=True,dedupe='daily:'+project+':'+day)
    result=run_queue(office.config().get('daily_team_tasks',4))
    office.report('plan'); return result

def snapshot():
    with office.db() as c:
        return {name:[dict(r) for r in c.execute('SELECT * FROM '+name)] for name in ['employees','office_missions','campaigns','employee_notes','handoffs','ceo_decisions']}

def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest='cmd',required=True)
    s.add_parser('init'); s.add_parser('status'); s.add_parser('daily')
    a=s.add_parser('campaign'); a.add_argument('project',choices=PROJECTS); a.add_argument('goal')
    a=s.add_parser('run'); a.add_argument('--limit',type=int,default=4); a.add_argument('--project',choices=PROJECTS)
    a=s.add_parser('decide'); a.add_argument('project',choices=PROJECTS); a.add_argument('decision'); a.add_argument('reason'); a.add_argument('--campaign')
    args=p.parse_args(); office.init()
    if args.cmd=='init': print('12 employees initialized')
    elif args.cmd=='status': print(json.dumps(snapshot(),ensure_ascii=False,indent=2))
    elif args.cmd=='campaign': print(json.dumps(create_campaign(args.project,args.goal),ensure_ascii=False))
    elif args.cmd=='run': print(json.dumps(run_queue(args.limit,args.project)))
    elif args.cmd=='daily': print(json.dumps(daily()))
    elif args.cmd=='decide': ceo_decide(args.project,args.decision,args.reason,args.campaign)

if __name__=='__main__': main()
