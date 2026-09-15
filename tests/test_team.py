import json,threading,unittest,re,urllib.request,urllib.error,urllib.parse
from unittest.mock import patch,MagicMock
from http.server import ThreadingHTTPServer
import office,team,orders,desk
import test_office

class TeamTests(unittest.TestCase):
    setUp=test_office.OfficeTests.setUp
    tearDown=test_office.OfficeTests.tearDown
    text=test_office.OfficeTests.text
    def roles(self):
        for role in ['CMO','CSO','CTO','CFO','CLO']:
            (office.ROOT/'company/roles'/f'{role}.md').write_text(role,encoding='utf-8')
    def test_separate_office_memory(self):
        office.memory('주문번호 비밀회사자료',project='baek')
        self.assertEqual(office.search('비밀회사자료','startup'),[])
        self.assertEqual(len(office.search('비밀회사자료','baek')),1)
    def test_cross_office_dependencies_denied(self):
        a=team.assign('baek_admin','a','b')
        with self.assertRaises(ValueError): team.assign('startup_chief','a','b',dependencies=[a])
    def test_cross_office_campaign_denied(self):
        camp=team.create_campaign('baek','a')['campaign_id']
        with self.assertRaises(ValueError): team.assign('startup_strategy','a','b',campaign=camp)
    def test_private_evidence_not_in_startup_prompt(self):
        self.roles(); path=office.ROOT/'private.md'; path.write_text('CUSTOMER_PRIVATE_TOKEN',encoding='utf-8')
        office.import_evidence(path,project='baek'); tid=team.assign('startup_strategy','市場','b')
        with office.db() as c: t=dict(c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone())
        self.assertNotIn('CUSTOMER_PRIVATE_TOKEN',office.context(t))
    def test_independent_employee_notes(self):
        with office.db() as c: c.execute('INSERT INTO employee_notes VALUES (?,?,?,?,?)',('x','startup_strategy','x','SECRET_PEER_DRAFT',office.now()))
        campaign=team.create_campaign('startup','test')
        with office.db() as c: t=dict(c.execute('SELECT * FROM tasks WHERE id=?',(campaign['drafts'][0],)).fetchone())
        self.assertNotIn('SECRET_PEER_DRAFT',team.employee_context(t))
        self.assertEqual(json.loads(t['dependencies']),[])
    def test_review_employee_is_distinct(self):
        self.roles(); tid=team.assign('baek_marketing','a','b'); seen=[]
        def call(provider,prompt,folder):
            seen.append(prompt)
            return {'status':'COMPLETED','text':'{"verdict":"PASS","issues":[],"reason":"ok"}' if len(seen)==2 else self.text()}
        with patch('office.invoke',side_effect=call): self.assertEqual(office.run_task(tid),'DONE')
        self.assertIn('직원 ID: baek_marketing',seen[0]); self.assertIn('직원 ID: baek_review',seen[1])
        with office.db() as c: self.assertEqual(c.execute("SELECT count(*) FROM employee_notes WHERE agent_id='baek_review'").fetchone()[0],1)
    def test_bounded_followup_chain_and_handoff(self):
        self.roles(); camp=team.create_campaign('baek','test')
        actions='\n```office-actions\n'+json.dumps({'actions':[{'agent_id':'baek_content','title':'후속 문서','brief':'명확한 완료 기준','kind':'document'}]})+'\n```'
        def call(provider,prompt,folder):
            return {'status':'COMPLETED','text':'{"verdict":"PASS","issues":[],"reason":"ok"}' if 'JSON만 반환:' in prompt else self.text()+actions}
        with patch('office.invoke',side_effect=call):
            team.run_queue(4,'baek')
            with office.db() as c: self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],5)
            team.process_followups(); team.run_queue(2,'baek'); team.process_followups()
        with office.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],5)
            self.assertEqual(c.execute("SELECT count(*) FROM tasks WHERE status='DONE'").fetchone()[0],5)
            a=c.execute('SELECT path FROM artifacts WHERE task_id=?',(camp['synthesis'],)).fetchone()
        prompt=(office.ROOT/a['path']).with_name('prompt.md').read_text(encoding='utf-8')
        self.assertIn('명시적으로 전달받은 동료 산출물',prompt)
        self.assertIn(camp['drafts'][0],prompt)
    def test_action_authority_scope(self):
        for action in [dict(agent_id='baek_admin',title='x',brief='x',kind='document'),dict(agent_id='startup_product',title='x',brief='x',kind='shell')]:
            body='```office-actions\n'+json.dumps({'actions':[action]})+'\n```'
            with self.assertRaises(ValueError): team.parse_actions(body,'startup')
    def test_ceo_kill_stops_campaign(self):
        cid=team.create_campaign('startup','test')['campaign_id']; team.ceo_decide('startup','KILL','stop',cid)
        self.assertEqual(team.ready_tasks('startup'),[])
        with office.db() as c: self.assertEqual(c.execute("SELECT count(*) FROM tasks WHERE status='CANCELLED'").fetchone()[0],4)
    def test_private_public_research_denied(self):
        with self.assertRaises(ValueError): team.assign('baek_marketing','a','b',kind='public_research')
    def test_public_web_trace_required(self):
        folder=office.ROOT/'trace'; folder.mkdir()
        final={'type':'result','subtype':'success','result':self.text(),'session_id':'independent-session'}
        proc=MagicMock(); proc.returncode=0; proc.communicate.return_value=(json.dumps(final),'')
        with patch('office.authentication',return_value=True),patch('office.executable',return_value='test'),patch('office.subprocess.Popen',return_value=proc):
            result=office.invoke('claude_code','public query',folder,public_research=True)
            self.assertEqual(result['status'],'FAILED')
            events=[{'message':{'content':[{'type':'tool_use','id':'w','name':'WebFetch','input':{'url':'https://example.org'}}]}},
                    {'message':{'content':[{'type':'tool_result','tool_use_id':'w','content':'source text'}]}},final]
            proc.communicate.return_value=('\n'.join(json.dumps(e) for e in events),'')
            result=office.invoke('claude_code','public query',folder,public_research=True)
            self.assertEqual(result['status'],'COMPLETED'); self.assertEqual(len(result['web_activity']['confirmed_tool_results']),1)
    def test_review_history_is_shared_with_new_reviewer(self):
        self.roles(); tid=team.assign('baek_marketing','history','brief'); prompts=[]
        values=[self.text(),'{"verdict":"REVISE","issues":["specific-observed-issue"],"reason":"fix"}',self.text(),'{"verdict":"PASS","issues":[],"reason":"fixed"}']
        def call(provider,prompt,folder):
            prompts.append(prompt); return {'status':'COMPLETED','text':values[len(prompts)-1]}
        with patch('office.invoke',side_effect=call):
            self.assertEqual(office.run_task(tid),'REVIEW'); office.retry(tid); self.assertEqual(office.run_task(tid),'DONE')
        self.assertIn('specific-observed-issue',prompts[3]); self.assertIn('관리자가 보관한 실제 이전 검수 기록',prompts[3])
        self.assertIn('수정 대상인 실제 직전 초안',prompts[2]); self.assertIn(self.text(),prompts[2])
    def test_daily_team_claim_is_idempotent(self):
        cfg=office.config(); cfg.update(automatic_execution=True,team_mode=True); office.dump(office.ROOT/'config.json',cfg)
        with patch('team.run_queue',return_value=[]) as run:
            team.daily(); self.assertEqual(team.daily(),'ALREADY_CLAIMED'); self.assertEqual(run.call_count,1)
        with office.db() as c:
            rows=c.execute('SELECT project,owner_agent,task_kind FROM tasks').fetchall()
            self.assertEqual({r['project'] for r in rows},{'baek','startup'}); self.assertTrue(all(r['task_kind']=='synthesis' for r in rows))
    def test_ceo_direction_creates_internal_plan(self):
        team.ceo_decide('startup','DIRECTION','먼저 고객 문제를 확인한다')
        with office.db() as c:
            row=c.execute('SELECT * FROM tasks').fetchone()
            self.assertEqual(row['owner_agent'],'startup_chief'); self.assertEqual(row['task_kind'],'synthesis')
            self.assertEqual(row['status'],'READY'); self.assertIn('고객 문제',row['prompt'])
    def test_tampered_handoff_is_rejected(self):
        self.roles(); tid=team.assign('baek_content','draft','brief',important=False)
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.text()}): office.run_task(tid)
        with office.db() as c: a=c.execute('SELECT * FROM artifacts WHERE task_id=?',(tid,)).fetchone()
        (office.ROOT/a['path']).write_text('tampered',encoding='utf-8')
        follow=team.assign('baek_chief','combine','brief',dependencies=[tid])
        with office.db() as c: task=dict(c.execute('SELECT * FROM tasks WHERE id=?',(follow,)).fetchone())
        with self.assertRaises(ValueError): team.employee_context(task)
    def test_queue_quota_and_pause(self):
        t=team.assign('startup_strategy','a','b')
        with office.db() as c: office.state(c,t,'WAITING_QUOTA')
        with patch('office.run_task') as run: self.assertEqual(team.run_queue(),[]); run.assert_not_called()
    def test_order_rows_and_ids_preserved(self):
        rows=[['주문번호','상품명','수량','연락처'],['0001','테스트떡','2','01000000000'],['0001','테스트떡','2','01000000000'],['0002','','abc',''],['0003','=1+1','0','']]
        data=orders.prepare(rows)
        self.assertEqual(data['row_count'],4); self.assertEqual(data['flagged_rows'],4)
        self.assertEqual(data['quantity_sum'],4); self.assertEqual(data['records'][0]['values'][0],'0001')
        self.assertEqual(data['records'][0]['values'][3],'01000000000')
        self.assertIn('완전 동일 행 의심',data['records'][0]['issues'])
    def test_ambiguous_column_fails(self):
        for rows in [[['주문번호','상품명','수량','수량'],['1','x','1','1']],[['order','상품명','수량'],['1','x','1']]]:
            with self.assertRaises(ValueError): orders.prepare(rows)
    def test_csv_encoding_and_blanks(self):
        path=office.ROOT/'x.csv'; path.write_bytes('주문번호,상품명,수량\n001,떡,1\n,,\n'.encode('cp949'))
        source,rows=orders.read_rows(path); data=orders.prepare(rows,source)
        self.assertEqual(data['row_count'],2); self.assertEqual(data['flagged_rows'],1)
    def test_http_csrf_host_and_ceo_decision(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),desk.handler_class(0)); port=server.server_port
        server.RequestHandlerClass=desk.handler_class(port)
        threading.Thread(target=server.serve_forever,daemon=True).start(); url=f'http://127.0.0.1:{port}'
        try:
            page=urllib.request.urlopen(url).read().decode(); token=re.search('name="token" value="([^"]+)"',page).group(1)
            self.assertIn('백년화편 업무 지원',page)
            for headers in [{'Origin':'https://evil.example'},{'Origin':url,'Host':'evil.example'}]:
                req=urllib.request.Request(url+'/decision',data=b'token=x',headers=headers)
                with self.assertRaises(urllib.error.HTTPError) as err: urllib.request.urlopen(req)
                self.assertEqual(err.exception.code,403)
                err.exception.close()
            payload=urllib.parse.urlencode({'token':token,'project':'baek','decision':'DIRECTION','reason':'마케팅 우선','campaign':''}).encode()
            req=urllib.request.Request(url+'/decision',data=payload,headers={'Origin':url})
            self.assertEqual(urllib.request.urlopen(req).status,200)
            with office.db() as c: self.assertEqual(c.execute('SELECT reason FROM ceo_decisions').fetchone()[0],'마케팅 우선')
        finally: server.shutdown(); server.server_close()
