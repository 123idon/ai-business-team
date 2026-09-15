import json,re,threading,unittest,urllib.request,urllib.parse
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import office,team,desk,meetings,meeting_ui,test_office

class MeetingTests(unittest.TestCase):
    setUp=test_office.OfficeTests.setUp
    tearDown=test_office.OfficeTests.tearDown
    def answer(self):
        return '# 의견\nMEETING_OPINION: 제공된 주문 양식부터 점검하는 것이 좋겠습니다. 현재 자료가 없으므로 실제 작업 완료나 조사 결과를 주장하지 않습니다.\n# 질문\n현재 사용 중인 양식은 무엇인가요? 고객 행을 회의에 붙이지 말고 로컬 주문 처리 기능을 사용하세요.\n# 다음 단계\n양식의 열 이름을 확인하고 누락 점검 기준을 제안하겠습니다. 아직 실행 승인이 확정된 것은 아닙니다.'
    def test_roundtrip_independent_and_reply(self):
        (office.ROOT/'company/roles/CMO.md').write_text('CMO')
        room,ids=meetings.post('baek','어떤 업무부터 맡길까요?',['baek_chief','baek_marketing'],request_id='one')
        self.assertEqual(len(set(ids)),2)
        self.assertIn('data-meeting-ready="false"',meeting_ui.transcript_html(room,'baek'))
        with self.assertRaises(ValueError): meetings.post('baek','premature',['baek_chief'],room_id=room)
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.answer()}) as model:
            results=meetings.run_turns(ids)
        self.assertEqual([x['status'] for x in results],['DONE','DONE']); self.assertEqual(model.call_count,2)
        self.assertNotIn('MEETING_OPINION',str(model.call_args_list[0]))
        self.assertIn('MEETING_OPINION',str(model.call_args_list[1]))
        data=meetings.transcript(room,'baek'); self.assertEqual(len(data['turns']),3)
        self.assertIn('MEETING_OPINION',data['turns'][1]['body'])
        self.assertIn('data-meeting-ready="true"',meeting_ui.transcript_html(room,'baek'))
        _,reply=meetings.post('baek','그 가정을 바꿔보세요',['baek_chief'],room_id=room)
        with office.db() as c:
            p=c.execute('SELECT prompt FROM tasks WHERE id=?',(reply[0],)).fetchone()[0]
            self.assertIn('MEETING_OPINION',p); self.assertIn('그 가정을 바꿔보세요',p)
            self.assertEqual(c.execute('SELECT count(*) FROM ceo_decisions').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM campaigns').fetchone()[0],0)
    def test_replay_and_office_separation(self):
        room,ids=meetings.post('baek','PRIVATE_BAEK',['baek_chief'],request_id='same')
        self.assertEqual(meetings.post('baek','PRIVATE_BAEK',['baek_chief'],request_id='same'),(room,ids))
        self.assertEqual(meetings.rooms('startup'),[])
        for op in [lambda:meetings.transcript(room,'startup'),lambda:meetings.post('baek','x',['startup_chief']),lambda:meetings.post('startup','x',['startup_chief'],room_id=room),lambda:meetings.post('startup','x',['startup_chief'],request_id='same')]:
            with self.assertRaises(ValueError): op()
        with office.db() as c: self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],1)
    def test_deleted_artifact_is_reported(self):
        room,ids=meetings.post('baek','question',['baek_chief'])
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.answer()}): meetings.run_turns(ids)
        with office.db() as c: path=c.execute('SELECT path FROM artifacts').fetchone()[0]
        (office.ROOT/path).unlink()
        self.assertEqual(meetings.transcript(room,'baek')['turns'][1]['status'],'FAILED')
    def test_assignment_idempotent_and_scoped(self):
        f={'agent':'baek_chief','title':'공통 제목','brief':'실제 지시문','request_id':'first'}
        tid,new=desk.assign_once('baek',f); self.assertTrue(new)
        self.assertEqual(desk.assign_once('baek',f),(tid,False))
        self.assertEqual(desk.assign_once('baek',dict(f,request_id='second')),(tid,False))
        with self.assertRaises(ValueError): desk.assign_once('startup',f)
        with office.db() as c: c.execute("UPDATE tasks SET status='DONE' WHERE id=?",(tid,))
        self.assertEqual(desk.assign_once('baek',f),(tid,False))
    def test_activity_matches_actual_run(self):
        t=team.assign('baek_chief','VISIBLE_TITLE','brief',important=False)
        def invoke(*args,**kwargs):
            self.assertIn('작성 중',meeting_ui.activity('baek'))
            self.assertIn('VISIBLE_TITLE',meeting_ui.activity('baek'))
            self.assertNotIn('VISIBLE_TITLE',meeting_ui.activity('startup'))
            return {'status':'COMPLETED','text':test_office.OfficeTests.text(self)}
        with patch('office.invoke',side_effect=invoke): office.run_task(t)
        self.assertIn('현재 실행 중인 AI 업무가 없습니다',meeting_ui.activity('baek'))
    def test_team_request_replay(self):
        one=team.create_campaign('baek','팀 목표',request_id='team-click')
        self.assertEqual(team.create_campaign('baek','팀 목표',request_id='team-click'),one)
        with office.db() as c: self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],4)
        with self.assertRaises(ValueError): team.create_campaign('startup','팀 목표',request_id='team-click')
    def test_direct_assignment_revision_stays_bounded(self):
        tid=team.assign('baek_chief','수정 대상','가설만 작성',important=True)
        response={'status':'COMPLETED','text':test_office.OfficeTests.text(self)}
        rejection={'status':'COMPLETED','text':'{"verdict":"REVISE","issues":["unsupported"],"reason":"revise"}'}
        with patch('office.invoke',side_effect=[response,rejection]*3) as model: outcomes=meetings.run_turns([tid],revise=True)
        self.assertEqual(len(outcomes),3); self.assertEqual(model.call_count,6)
        with office.db() as c:
            row=c.execute('SELECT status,revisions FROM tasks WHERE id=?',(tid,)).fetchone()
        self.assertEqual(tuple(row),('REVIEW',2))
    def test_busy_background_keeps_next_job(self):
        started=threading.Event(); release=threading.Event(); finished=threading.Event(); seen=[]
        def first(): started.set(); release.wait(3); seen.append('first')
        def second(): seen.append('second'); finished.set()
        desk.background(first)
        try:
            self.assertTrue(started.wait(2)); desk.background(second)
            self.assertFalse(finished.is_set()); release.set(); self.assertTrue(finished.wait(2))
            self.assertEqual(seen,['first','second'])
        finally: release.set()
    def test_http_assignment_receipt_live_and_meeting(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),desk.handler_class(0))
        port=server.server_port; server.RequestHandlerClass=desk.handler_class(port)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        base=f'http://127.0.0.1:{port}'
        try:
            page=urllib.request.urlopen(base+'/?office=baek').read().decode()
            token=re.search('name="token" value="([^"]+)"',page)[1]
            def post(path,data):
                req=urllib.request.Request(base+path,data=urllib.parse.urlencode(dict(token=token,project='baek',**data)).encode(),headers={'Origin':base})
                return urllib.request.urlopen(req).read().decode()
            with patch('desk.background') as dispatch:
                reply=post('/assign',dict(agent='baek_chief',title='HTTP_TITLE',brief='HTTP_BRIEF',request_id='click',start_now='1'))
                self.assertIn('배정 완료',reply); self.assertEqual(dispatch.call_count,1)
                reply=post('/assign',dict(agent='baek_chief',title='HTTP_TITLE',brief='HTTP_BRIEF',request_id='click',start_now='1'))
                self.assertIn('중복 배정하지 않았습니다',reply)
                reply=post('/meeting-start',dict(message='회의 안건',title='HTTP_MEETING',participant_baek_chief='1',request_id='room'))
                self.assertIn('HTTP_MEETING',reply); self.assertIn('발언 순서를 기다리는 중',reply)
                room=meetings.rooms('baek')[0]['id']
                ids=[t['task_id'] for t in meetings.transcript(room,'baek')['turns'] if t['task_id']]
                with patch('office.invoke',return_value={'status':'COMPLETED','text':self.answer()}): meetings.run_turns(ids)
                reply=post('/meeting-reply',dict(room=room,message='HTTP_FOLLOWUP',participant_baek_chief='1',request_id='reply'))
                self.assertIn('HTTP_FOLLOWUP',reply); self.assertIn('MEETING_OPINION',reply)
            with office.db() as c: self.assertEqual(c.execute("SELECT count(*) FROM tasks WHERE title='HTTP_TITLE'").fetchone()[0],1)
            response=urllib.request.urlopen(base+'/live?office=baek')
            self.assertIn("connect-src 'self'",response.headers['Content-Security-Policy'])
            data=json.load(response); self.assertIn('HTTP_TITLE',data['live-tasks'])
            self.assertIn('회의 안건',data['meeting-transcript'])
        finally: server.shutdown(); server.server_close(); thread.join()
