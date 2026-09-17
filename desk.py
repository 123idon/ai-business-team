"""Loopback human CEO desk. No external actions or model-facing mutation API."""
import html, json, re, secrets, threading, collections
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit, urlencode
import office, team, orders, advisor, meetings, meeting_ui, briefings

BUSY=threading.Lock()
PENDING=collections.deque()
ASSIGN_LOCK=threading.Lock()
JOB={'status':'대기','detail':''}

def assign_once(project,fields):
    agent=fields['agent']; title=fields['title'][:200]; brief=fields['brief'][:8000]
    if team.employee(agent)['project']!=project: raise ValueError('다른 사무실 직원입니다.')
    if not title.strip() or not brief.strip(): raise ValueError('제목과 지시문을 적어주세요.')
    key='uiassign:'+fields.get('request_id',office.uid())
    with ASSIGN_LOCK:
        with office.db() as c:
            existing=c.execute('SELECT id,project FROM tasks WHERE dedupe_key=?',(key,)).fetchone()
            if existing and existing['project']!=project: raise ValueError('다른 사무실 요청입니다.')
            if not existing:
                existing=c.execute("SELECT id FROM tasks WHERE project=? AND owner_agent=? AND title=? AND prompt=? AND status IN ('READY','RUNNING','REVIEW') ORDER BY created LIMIT 1",(project,agent,title,brief)).fetchone()
        if existing: return existing['id'],False
        kind='public_research' if agent=='startup_research' else 'document'
        return team.assign(agent,title,brief,kind=kind,dedupe=key),True
def esc(value): return html.escape(str(value),quote=True)
def background(fn):
    with ASSIGN_LOCK:
        PENDING.append(fn)
        if not BUSY.acquire(False): return
    JOB.update(status='진행 중',detail='접수한 작업을 순서대로 진행합니다.')
    def worker():
        while True:
            with ASSIGN_LOCK:
                if not PENDING: BUSY.release(); return
                job=PENDING.popleft()
            try:
                JOB.update(status='진행 중',detail='접수한 작업을 순서대로 진행합니다.')
                result=job(); JOB.update(status='완료',detail=str(result)[:1800])
            except Exception as err: JOB.update(status='확인 필요',detail=str(err)[:1800])
    threading.Thread(target=worker,daemon=True).start()

def render(project,token,fragments=False,room_id=None,notice=''):
    if project not in team.PROJECTS: project='baek'
    s=office.snapshot(); ts=team.snapshot(); cfg=office.config()
    tasks=[t for t in s['tasks'] if t['project']==project]
    employees=[e for e in ts['employees'] if e['project']==project]
    names={e['id']:e['name'] for e in employees}
    titles={t['id']:t['title'] for t in tasks}
    states={'READY':'실행 대기','RUNNING':'일하는 중','REVIEW':'수정·검수 대기','DONE':'완료','FAILED':'실패 확인 필요',
      'WAITING_QUOTA':'구독 한도 대기','NEEDS_LOGIN':'로그인 필요','WAITING_EXTERNAL':'입력·실행 조건 대기','CANCELLED':'중단','BLOCKED':'실행 차단','WAITING_HUMAN':'사람 확인 필요'}
    def form(action,body,multipart=False):
        start='<label><input style="width:auto;display:inline" type="checkbox" name="start_now" value="1" checked>배정 후 바로 실행</label>' if action in {'assign','campaign'} else ''
        return f'<form method="post" action="/{action}"'+(' enctype="multipart/form-data"' if multipart else '')+f'><input type="hidden" name="request_id" value="{office.uid()}"><input type="hidden" name="token" value="{token}"><input type="hidden" name="project" value="{project}">{body}{start}</form>'
    employee_cards=''
    for e in employees:
        own=[t for t in tasks if t['owner_agent']==e['id']]
        current=next((t for t in own if t['status']=='RUNNING'),None)
        note=next((n for n in reversed(ts['employee_notes']) if n['agent_id']==e['id']),None)
        activity='일하는 중' if current else '실행 대기 '+str(sum(t['status']=='READY' for t in own))+'건'
        completed='완료 '+str(sum(t['status']=='DONE' for t in own))+'건'
        if e['id'].endswith('_review'):
            reviews=[r for r in s['runs'] if r['task_id'] in titles and r['purpose']=='review']
            activity='검수 중' if any(r['status']=='RUNNING' for r in reviews) else '검수 배정 대기'
            completed='사무실 검수 기록 '+str(sum(r['status']=='COMPLETED' for r in reviews))+'회'
        employee_cards+=f'<article><h3>{esc(e["name"])}</h3><p>{esc(e["responsibility"])}</p><small>{activity} · {completed}</small><details><summary>최근 업무 기억</summary><p>{esc(note["summary"] if note else "결과와 검수 의견은 아래 업무 기록에서 확인합니다.")}</p></details></article>'
    artifacts={}
    purposes={r['id']:r['purpose'] for r in s['runs']}
    latest={}
    for a in s['artifacts']:
        if a['task_id'] in titles: latest[(a['task_id'],purposes[a['run_id']])]=a
    for a in latest.values(): artifacts.setdefault(a['task_id'],[]).append(a)
    rows=''
    for t in reversed(tasks):
        links=' '.join(f'<a href="/artifact/{a["id"]}">{"검수 의견" if purposes[a["run_id"]]=="review" else ("결과" if a["verified"] else "초안")}</a>' for a in artifacts.get(t['id'],[]))
        retry=''
        if t['status'] in {'REVIEW','FAILED','WAITING_EXTERNAL','WAITING_QUOTA','NEEDS_LOGIN','BLOCKED','WAITING_HUMAN'}:
            retry=form('retry',f'<input type="hidden" name="task" value="{t["id"]}"><button class="small">점검 후 재시도 대기</button>') if t['revisions']<cfg['max_revision_rounds'] else '<p class="muted">수정 한도 도달 · 새 자료나 구체적인 지침이 필요합니다.</p>'
        rows+=f'<tr><td>{esc(t["title"])}</td><td>{esc(names.get(t["owner_agent"],t["role"]))}</td><td>{esc(states.get(t["status"],t["status"]))}{retry}</td><td>{links}</td></tr>'
    options=''.join(f'<option value="{e["id"]}">{esc(e["name"])}</option>' for e in employees if not e['id'].endswith(('_review','_advisor')))
    examples=('마케팅과 주문 정리가 겹쳐 바빠. 오늘 무엇을 누구에게 맡기면 좋을까?' if project=='baek' else '창업하고 싶은데 아직 아이템이 없어. 직원들에게 무엇부터 시키면 좋을까?')
    advice_section='<section id="advisor"><h2>무엇을 어떻게 맡길지, 조언자에게 물어보세요</h2><p>막연한 고민도 괜찮습니다. 지금 맡길 일·담당 직원·진행 방식·준비 자료를 추천하고 지시문을 써 드립니다.</p>'
    advice_section+=form('advisor',f'<label>현재 상황과 하고 싶은 일<textarea name="question" maxlength="8000" required placeholder="{esc(examples)}"></textarea></label><p class="muted">고객 이름·연락처·주문 행은 여기에 붙여 넣지 마세요. 상담은 현재 선택한 사무실의 기록만 참고합니다.</p><button>조언과 지시문 추천받기</button>')
    advice_section+='<p class="muted">추천받기만으로 업무가 배정되지는 않습니다. 상담이 끝나면 새로고침하고 추천 지시문을 확인하세요.</p>'
    for history_index,item in enumerate(advisor.latest(project)):
        advice_section+=f'<details {"open" if history_index==0 else ""}><summary>{esc(item["question"])}</summary><details><summary>전체 조언과 확인 질문 보기</summary><p style="white-space:pre-wrap">{esc(item["explanation"])}</p></details>'
        for index,p in enumerate(item['proposals'],1):
            label={'single':'직원 한 명에게 지시','team':'팀 협업으로 진행','orders':'로컬 주문지 정리'}[p['mode']]
            advice_section+=f'<article><h3>{index}. {esc(p["title"])}</h3><p>{esc(p["reason"])}</p><p>추천 담당: {esc(names[p["agent_id"]])} · {label}</p><p>준비 자료: {esc(" / ".join(p["materials"]) or "추가 자료 없이 시작 가능")}</p>'
            if p['mode']=='orders':
                advice_section+=f'<p style="white-space:pre-wrap">{esc(p["brief"])}</p><a href="#orders">주문 파일 선택하러 가기</a>'
            elif p['mode']=='team':
                advice_section+=form('campaign',f'<label>수정해서 사용할 팀 지시문<textarea name="goal" maxlength="8000" required>{esc(p["brief"])}</textarea></label><button>이 지시문으로 팀에 배정</button>')
            else:
                advice_section+=form('assign',f'<input type="hidden" name="agent" value="{p["agent_id"]}"><label>업무 제목<input name="title" maxlength="200" value="{esc(p["title"])}" required></label><label>수정해서 사용할 지시문<textarea name="brief" maxlength="8000" required>{esc(p["brief"])}</textarea></label><button>이 지시문으로 직원에게 배정</button>')
            advice_section+='</article>'
        advice_section+='</details>'
    advice_section+='</section>'
    camps=[c for c in ts['campaigns'] if c['project']==project]
    campopts='<option value="">사무실 전체 지침</option>'+''.join(f'<option value="{c["id"]}">{esc(c["goal"][:65])}</option>' for c in camps)
    decisions=''.join(f'<li>{esc(d["decision"])} · {esc(d["reason"])}</li>' for d in ts['ceo_decisions'] if d['project']==project)
    pause=(office.ROOT/'data/STOP').exists()
    tools=form('run','<button>직원 업무 실행 · 최대 4건</button>')+form('resume' if pause else 'pause','<button class="secondary">'+('자동 업무 재개' if pause else '현재 업무 후 멈추기')+'</button>')
    order_section=''
    if project=='baek':
        downloads=''.join(f'<li><a href="/orders/{r["id"]}">정리된 주문지 받기</a> · {r["rows"]}행 · 점검 {r["flagged"]}행</li>' for r in orders.receipts())
        order_section='<section><h2>주문지 정리</h2><p>고객 행은 이 PC에서 처리합니다. 원본과 모든 행을 보존하고, 누락·잘못된 수량·완전 동일 행 의심을 표시합니다.</p><p class="muted">첫 행에 주문번호·상품명·수량 제목이 있는 단일 표. .xlsx 또는 .csv, 최대 20MB·10,000행. 수식·여러 데이터 시트는 값만 담은 사본으로 준비하세요.</p>'+form('orders','<label>주문 파일<input type="file" name="file" accept=".xlsx,.csv" required></label><button>로컬에서 정리</button>',True)+f'<ul>{downloads}</ul></section>'
    order_section=order_section.replace('<section>','<section id="orders">',1)
    meeting_section,transcript=meeting_ui.section(project,form,room_id)
    active=meeting_ui.activity(project)
    chief_report=briefings.panel(project)
    if fragments: return {'live-chief-report':chief_report,'live-activity':active,'live-employees':employee_cards,'live-tasks':rows,'meeting-transcript':transcript}
    notice_html='<p role="status" class="status">'+esc(notice)+'</p>' if notice else ''
    return f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>AI 사무실 v1</title>
<style>body{{font:16px system-ui,sans-serif;margin:0;background:#f4f3ef;color:#20313d}}main{{max-width:1200px;margin:auto;padding:32px 24px}}nav{{display:flex;gap:12px;flex-wrap:wrap}}a{{color:#1f5f83}}nav a{{padding:12px 18px;background:white;border-radius:8px;text-decoration:none}}nav .active{{background:#233d59;color:white}}header{{padding:16px 0 24px;border-bottom:1px solid #d5d9d8}}h1{{font-size:36px;margin-bottom:8px}}h2{{font-size:23px}}h3{{margin:0}}p{{line-height:1.65}}.muted,small{{color:#536773}}.staff{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}}article,section{{background:white;padding:22px;border-radius:12px;margin-top:18px}}article p{{font-size:14px}}.bar{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}}.bar form{{margin:0}}button{{background:#233d59;color:white;border:0;padding:12px 16px;border-radius:7px;font:inherit;cursor:pointer}}button.secondary{{background:#e6eae9;color:#20313d}}button.small{{font-size:12px;padding:5px;margin-top:6px}}textarea,input:not([type=hidden]),select{{box-sizing:border-box;display:block;width:100%;max-width:800px;font:inherit;border:1px solid #a9b6be;border-radius:6px;padding:10px;margin:8px 0 14px}}textarea{{min-height:95px}}label{{display:block;margin:12px 0}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #e0e5e6}}.scroll{{overflow:auto}}details p{{max-height:200px;overflow:auto}}.status{{border-left:4px solid #b48b45;padding-left:16px}}.twocol{{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:18px}}li{{margin:10px 0}}code{{overflow-wrap:anywhere}}</style>
<style>#chief-report{{border-top:5px solid #233d59}}.chief-copy{{max-width:920px}}.chief-copy h3{{margin:26px 0 10px;color:#1f5f83;font-size:20px}}.chief-copy p{{font-size:16px;line-height:1.85;margin:10px 0;overflow-wrap:anywhere}}</style>
<main><nav><a class="{'active' if project=='baek' else ''}" href="/?office=baek">백년화편 업무 지원</a><a class="{'active' if project=='startup' else ''}" href="/?office=startup">신규 스타트업 사무실</a></nav>
<header><p class="muted">AI 사무실 v1 · 인간 CEO의 업무실</p><h1>{team.PROJECTS[project]}</h1><p>직원별로 생각하고, 결과를 전달하고, 별도 검수를 거칩니다.</p><small>주 실행 {'Claude Code' if cfg['primary']=='claude_code' else 'Codex'} · 검수 Codex · 추가 모델 API 없음</small></header>
{notice_html}<section id="chief-report"><h2>업무실장 종합 보고</h2><div id="live-chief-report">{chief_report}</div>{form('briefing','<button>최신 결과로 종합 보고 정리</button>')}</section>
<section id="activity"><h2>지금 직원들이 하는 일</h2><div id="live-activity">{active}</div><small id="connection-state">실제 작업 기록으로 자동 갱신합니다.</small></section>
<p class="status">{'자동 업무 일시정지' if pause else '자동 업무 활성'} · 매일 09:00 두 사무실 합계 최대 {cfg.get('daily_team_tasks',4)}건 · 18:00 마감 보고</p><details><summary>최근 실행 상세</summary><p>{esc(JOB['detail'])}</p></details><div class="bar">{tools}</div>
{meeting_section}{advice_section}<details><summary>직원 {len(employees)}명 · 개별 현황 보기</summary><div class="staff" id="live-employees">{employee_cards}</div></details>
<div class="twocol"><section><h2>함께 고민할 목표</h2><p>직원 3명이 독립 검토하고 실장이 종합합니다. 검수 통과 후 내부 후속 업무를 최대 2개 배정합니다.</p>{form('campaign','<label>목표와 완료 기준<textarea name="goal" maxlength="8000" required placeholder="예: 이번 주 마케팅 업무를 정리하고 실행 초안까지 만들어줘"></textarea></label><button>팀에 목표 배정</button>')}</section>
<section><h2>직원에게 직접 지시</h2>{form('assign','<label>담당 직원<select name="agent">'+options+'</select></label><label>업무 제목<input name="title" maxlength="200" required></label><label>입력 자료와 완료 기준<textarea name="brief" maxlength="8000" required></textarea></label><button>업무 배정</button>')}</section></div>
{order_section}<section class="scroll" id="tasks"><h2>업무와 결과</h2>{notice_html}<p>결론은 위의 업무실장 종합 보고에서 확인하세요.</p><details><summary>개별 업무·원문·검수 기록 펼치기</summary><table><thead><tr><th>업무</th><th>담당</th><th>상태</th><th>결과</th></tr></thead><tbody id="live-tasks">{rows}</tbody></table></details></section>
<section><h2>인간 CEO 결정</h2><p>우선순위와 방향을 직원 기억에 전달합니다. 특정 목표의 중단을 선택하면 그 목표의 대기 업무를 취소합니다.</p>{form('decision','<label>대상<select name="campaign">'+campopts+'</select></label><label>결정<select name="decision"><option value="DIRECTION">방향 지시</option><option value="PRIORITY">우선순위</option><option value="ITERATE">수정·재검토</option><option value="SIMPLIFY">범위 축소</option><option value="SCALE">확대 방향</option><option value="KILL">해당 목표 중단</option></select></label><label>이유와 구체적인 지침<textarea name="reason" maxlength="8000" required></textarea></label><button>내 결정 기록</button>')}<ul>{decisions or '<li>등록된 CEO 결정 없음</li>'}</ul></section>
<section><h2>구독 구성</h2><p>구독 전환 후 Codex 단독을 선택하면 직원과 기록은 유지되고 실행 도구만 바뀝니다.</p>{form('provider','<select name="primary"><option value="claude_code">Claude 실행 + Codex 검수</option><option value="codex_cli">Codex 단독 · 별도 세션 검수</option></select><button>실행 도구 변경</button>')}</section>
<p class="muted">PC가 켜져 있고 사용자 로그인 상태일 때 실행됩니다. AI 직원은 매 작업마다 새 세션으로 호출되며, 업무 기억은 사무실에 남습니다. v1 실행 범위는 문서 작성·공개 조사·주문지 정리입니다. 외부 발송·게시·결제 기능은 연결되어 있지 않습니다.</p></main><script src="/desk_live.js" defer></script></html>'''

def handler_class(port):
    token=secrets.token_urlsafe(32)
    hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
    class Handler(BaseHTTPRequestHandler):
        def send(self,content,status=200,mime='text/html; charset=utf-8',download=False):
            raw=content.encode('utf-8') if isinstance(content,str) else content
            self.send_response(status); self.send_header('Content-Type',mime)
            self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
            if download: self.send_header('Content-Disposition','attachment; filename="orders.xlsx"')
            self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            if self.headers.get('Host') not in hosts: self.send_error(403); return
            url=urlsplit(self.path)
            if url.path in {'/','/live'}:
                q=parse_qs(url.query); p=q.get('office',['baek'])[0]
                try:
                    result=render(p,token,fragments=url.path=='/live',room_id=q.get('meeting',[None])[0],notice=q.get('notice',[''])[0][:400])
                    self.send(json.dumps(result,ensure_ascii=False) if url.path=='/live' else result,mime='application/json; charset=utf-8' if url.path=='/live' else 'text/html; charset=utf-8')
                except ValueError as err: self.send(esc(err),404)
                return
            if url.path=='/desk_live.js': self.send((office.ROOT/'desk_live.js').read_bytes(),mime='text/javascript; charset=utf-8'); return
            if re.fullmatch('/artifact/[a-f0-9]{32}',url.path):
                with office.db() as c: a=c.execute('SELECT * FROM artifacts WHERE id=?',(url.path.rsplit('/',1)[1],)).fetchone()
                if not a: self.send_error(404); return
                path=(office.ROOT/a['path']).resolve()
                if not path.is_relative_to((office.ROOT/'runs').resolve()) or not path.is_file(): self.send_error(404); return
                if office.digest(path.read_bytes())!=a['sha256']: self.send_error(409); return
                self.send('<meta charset="utf-8"><a href="/">사무실로</a><pre style="white-space:pre-wrap;max-width:1000px;margin:30px auto;font:17px/1.8 system-ui">'+esc(path.read_text(encoding='utf-8'))+'</pre>'); return
            if re.fullmatch('/orders/[a-f0-9]{32}',url.path):
                a=next((a for a in orders.receipts() if a['id']==url.path.rsplit('/',1)[1]),None)
                if not a: self.send_error(404); return
                path=(office.ROOT/a['path']).resolve()
                if not path.is_relative_to((office.ROOT/'orders').resolve()) or not path.is_file(): self.send_error(404); return
                if office.digest(path.read_bytes())!=a['sha256']: self.send_error(409); return
                self.send(path.read_bytes(),mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',download=True); return
            self.send_error(404)
        def do_POST(self):
            if self.headers.get('Host') not in hosts or self.headers.get('Origin') not in {'http://'+h for h in hosts}:
                self.send_error(403); return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size<=0 or size>21*1024*1024: raise ValueError('파일 크기 제한 20MB를 확인하세요.')
                raw=self.rfile.read(size); upload=None; fields={}
                ctype=self.headers.get('Content-Type','')
                if ctype.startswith('multipart/form-data'):
                    message=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+ctype+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
                    for part in message.iter_parts():
                        name=part.get_param('name',header='content-disposition')
                        if name=='file': upload=(part.get_filename(),part.get_payload(decode=True))
                        else: fields[name]=part.get_payload(decode=True).decode('utf-8')
                else: fields={k:v[0] for k,v in parse_qs(raw.decode('utf-8'),keep_blank_values=True).items()}
                if not secrets.compare_digest(fields.get('token',''),token):
                    self.send('<meta charset="utf-8"><p>사무실이 재시작되어 이 화면의 접수 시간이 만료되었습니다. 새 화면을 열고 다시 보내주세요.</p><a href="/">새 화면 열기</a>',403); return
                p=fields.get('project')
                if p not in team.PROJECTS: raise ValueError('사무실을 선택하세요.')
                notice='요청을 접수했습니다.'; anchor='activity'; room=None
                if self.path=='/advisor': background(lambda:advisor.ask(p,fields['question']))
                elif self.path=='/briefing':
                    background(lambda:briefings.refresh(p)); notice='업무실장에게 최신 결과의 종합 보고를 요청했습니다.'; anchor='chief-report'
                elif self.path=='/run': background(lambda:team.run_queue(4,p))
                elif self.path=='/campaign':
                    cid=team.create_campaign(p,fields['goal'][:8000],request_id=fields.get('request_id'))
                    notice='팀 목표를 배정했습니다. 업무 목록에서 담당자와 상태를 확인하세요.'; anchor='tasks'
                    if fields.get('start_now')=='1': background(lambda:team.run_queue(4,p))
                elif self.path=='/assign':
                    tid,created=assign_once(p,fields)
                    notice=('배정 완료' if created else '이미 접수된 같은 업무입니다. 중복 배정하지 않았습니다.')+' · 업무 번호 '+tid
                    if fields.get('start_now')=='1':
                        background(lambda:meetings.run_turns([tid],revise=True)); notice+=' · 실행을 요청했습니다.'
                    else: notice+=' · 실행 대기 목록에 저장했습니다.'
                    anchor='tasks'
                elif self.path in {'/meeting-start','/meeting-reply'}:
                    participants=[k[len('participant_'):] for k,v in fields.items() if k.startswith('participant_') and v=='1']
                    room,ids=meetings.post(p,fields['message'],participants,room_id=fields.get('room') if self.path=='/meeting-reply' else None,title=fields.get('title',''),request_id=fields.get('request_id'))
                    background(lambda:meetings.run_turns(ids))
                    notice='회의 발언을 접수했습니다. 선택한 직원이 순서대로 답하며, 도착한 의견은 자동으로 표시됩니다.'; anchor='meeting'
                elif self.path=='/decision':
                    if fields['decision']=='KILL' and not fields.get('campaign'): raise ValueError('중단할 목표를 선택하세요.')
                    team.ceo_decide(p,fields['decision'],fields['reason'][:8000],fields.get('campaign') or None)
                elif self.path=='/retry':
                    with office.db() as c: row=c.execute('SELECT project FROM tasks WHERE id=?',(fields['task'],)).fetchone()
                    if not row or row['project']!=p: raise ValueError('다른 사무실 업무입니다.')
                    office.retry(fields['task'])
                elif self.path=='/pause': (office.ROOT/'data/STOP').write_text(office.now(),encoding='utf-8')
                elif self.path=='/resume': (office.ROOT/'data/STOP').unlink(missing_ok=True)
                elif self.path=='/provider':
                    if fields['primary'] not in {'claude_code','codex_cli'}: raise ValueError('지원하지 않는 실행 도구입니다.')
                    with office.lock():
                        cfg=office.config(); cfg['primary']=fields['primary']; office.dump(office.ROOT/'config.json',cfg)
                elif self.path=='/orders':
                    if p!='baek' or not upload or not upload[0] or not upload[1]: raise ValueError('주문 파일을 선택하세요.')
                    suffix=office.Path(upload[0]).suffix.lower()
                    if suffix not in {'.xlsx','.csv'} or len(upload[1])>20*1024*1024: raise ValueError('.xlsx 또는 .csv 20MB 이하만 지원합니다.')
                    path=office.ROOT/'inbox/baek'/(office.uid()+suffix); path.write_bytes(upload[1])
                    background(lambda:orders.process(path))
                else: self.send_error(404); return
                query={'office':p,'notice':notice}
                if room: query['meeting']=room
                self.send_response(303); self.send_header('Location','/?'+urlencode(query)+'#'+anchor); self.end_headers()
            except Exception as err: self.send('<meta charset="utf-8"><a href="/">사무실로 돌아가기</a><p>'+esc(err)+'</p>',400)
        def log_message(self,*args): pass
    return Handler

def serve(port=8765):
    ThreadingHTTPServer(('127.0.0.1',port),handler_class(port)).serve_forever()
