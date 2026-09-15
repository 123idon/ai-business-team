import datetime as dt,html
import office,team,meetings
def e(x): return html.escape(str(x),quote=True)

def activity(project):
    with office.db() as c:
        active=[dict(r) for r in c.execute("SELECT r.purpose,r.started,t.title,t.owner_agent FROM runs r JOIN tasks t ON r.task_id=t.id WHERE r.status='RUNNING' AND t.project=?",(project,))]
        counts=dict(c.execute('SELECT status,count(*) FROM tasks WHERE project=? GROUP BY status',(project,)).fetchall())
        names={r['id']:r['name'] for r in c.execute('SELECT id,name FROM employees WHERE project=?',(project,))}
        waits=[dict(r) for r in c.execute("SELECT title,status FROM tasks WHERE project=? AND status IN ('WAITING_QUOTA','NEEDS_LOGIN','FAILED','WAITING_EXTERNAL') ORDER BY updated DESC LIMIT 3",(project,))]
    lines=[]
    for row in active:
        seconds=max(0,int((dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(row['started'])).total_seconds()))
        who=names.get(project+'_review' if row['purpose']=='review' else row['owner_agent'],'직원')
        lines.append(f'<p><strong>{e(who)} · {"검수 중" if row["purpose"]=="review" else "작성 중"}</strong><br>{e(row["title"])} · 시작 후 {seconds//60}분 {seconds%60}초</p>')
    if not lines: lines=['<p>현재 실행 중인 AI 업무가 없습니다.</p>']
    lines.append(f'<p>실행 대기 {counts.get("READY",0)}건 · 수정·검수 대기 {counts.get("REVIEW",0)}건 · 완료 {counts.get("DONE",0)}건</p>')
    if (office.ROOT/'data/STOP').exists(): lines.append('<p>일시정지 상태입니다. 재개해야 새 작업이 시작됩니다.</p>')
    status={'WAITING_QUOTA':'구독 한도 대기','NEEDS_LOGIN':'로그인 필요','FAILED':'실행 실패','WAITING_EXTERNAL':'입력·실행 조건 확인 필요'}
    lines.extend('<p>'+e(status[r['status']])+' · '+e(r['title'])+'</p>' for r in waits)
    return ''.join(lines)

def transcript_html(room_id,project):
    if not room_id: return '<p>회의를 시작하면 인간 CEO와 직원의 발언이 여기에 쌓입니다.</p>'
    data=meetings.transcript(room_id,project)
    names={x[0]:x[2] for x in team.STAFF}; names['human']='나 · 인간 CEO'
    pending=any(t['status'] in {'READY','RUNNING'} for t in data['turns'])
    out=f'<div data-meeting-ready="{str(not pending).lower()}"></div>'
    statuses={'READY':'발언 순서를 기다리는 중','RUNNING':'의견 작성 중','REVIEW':'발언 형식 확인 필요','FAILED':'발언 생성 실패','WAITING_QUOTA':'구독 한도 대기','NEEDS_LOGIN':'로그인 필요','WAITING_EXTERNAL':'실행 조건 확인 필요','CANCELLED':'취소'}
    for t in data['turns']:
        body=t['body'] if t['status'] in {'DONE','POSTED'} else statuses.get(t['status'],t['status'])
        out+=f'<article><strong>{e(names.get(t["speaker"],t["speaker"]))}</strong><p style="white-space:pre-wrap">{e(body)}</p></article>'
    return out

def section(project,form,room_id=None):
    rooms=meetings.rooms(project)
    if room_id and room_id not in {r['id'] for r in rooms}: raise ValueError('다른 사무실 또는 없는 회의입니다.')
    if not room_id and rooms: room_id=rooms[0]['id']
    people=[a for a in team.STAFF if a[1]==project and not a[0].endswith('_advisor')]
    defaults={project+'_chief','baek_marketing' if project=='baek' else 'startup_strategy'}
    def participants():
        return '<fieldset><legend>발언할 직원 · 한 번에 1~3명</legend>'+''.join(f'<label style="display:inline-block;margin-right:15px"><input style="width:auto;display:inline" type="checkbox" name="participant_{a[0]}" value="1" {"checked" if a[0] in defaults else ""}>{e(a[2])}</label>' for a in people)+'</fieldset>'
    out=f'<section id="meeting" data-room="{e(room_id or "")}"><h2>직원 회의실</h2><p>안건을 꺼내고 직원들의 의견에 답하거나 반론·추가 질문을 보낼 수 있습니다. 직원은 한 명씩 별도 세션에서 발언합니다. 회의 의견은 실행 승인이나 사업 확정으로 처리되지 않습니다.</p>'
    out+='<details '+('open' if not room_id else '')+'><summary>새 회의 시작</summary>'+form('meeting-start','<label>회의 제목<input name="title" maxlength="150" required></label><label>안건과 내 의견<textarea name="message" maxlength="8000" required></textarea></label>'+participants()+'<button>회의 시작 · 직원 의견 듣기</button>')+'</details>'
    out+='<p>'+ ' · '.join(f'<a href="/?office={project}&meeting={r["id"]}#meeting">{e(r["title"])}</a>' for r in rooms[:12])+'</p>'
    transcript=transcript_html(room_id,project)
    if room_id:
        title=next(r['title'] for r in rooms if r['id']==room_id)
        out+='<h3>'+e(title)+'</h3>'
    out+='<div id="meeting-transcript">'+transcript+'</div>'
    if room_id:
        pending='data-meeting-ready="false"' in transcript
        out+=form('meeting-reply',f'<input type="hidden" name="room" value="{room_id}"><label>내 답변·반론·추가 질문<textarea name="message" maxlength="8000" required placeholder="예: 그 가정에는 동의하지 않아. 다른 가능성은 없을까?"></textarea></label>'+participants()+f'<button class="meeting-send" {"disabled" if pending else ""}>{"직원 발언을 기다리는 중" if pending else "내 의견 보내고 답변 듣기"}</button>')
    return out+'</section>',transcript
