import json, os, sqlite3, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
import office

class OfficeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.old=office.ROOT; office.ROOT=Path(self.temp.name)
        (office.ROOT/'company/roles').mkdir(parents=True)
        for name in ['charter.md','procedures.md']:
            (office.ROOT/'company'/name).write_text('test policy',encoding='utf-8')
        (office.ROOT/'company/roles/CEO.md').write_text('CEO',encoding='utf-8')
        (office.ROOT/'config.json').write_text(json.dumps({'primary':'claude_code','reviewer':'codex_cli',
          'max_revision_rounds':2,'timeout_seconds':2,'paid_model_api_enabled':False,'automatic_paid_fallback':False}))
        office.init()
    def tearDown(self): office.ROOT=self.old; self.temp.cleanup()
    def task(self,important=False): return office.add('시장 검증','가설만 작성',important=important)
    def status(self,t):
        with office.db() as c: return c.execute('SELECT status FROM tasks WHERE id=?',(t,)).fetchone()[0]
    def text(self): return '# 가정\n미확인 가설입니다.\n# 근거\n외부 조사 없음.\n# 미확인\n확인할 사실이 많습니다.\n# 실험\n작은 규모의 인터뷰를 기획합니다. 비용과 외부 전송은 아직 실행하지 않습니다.\n# 완료 기준\n검증할 가정과 질문이 제시되면 문서 과제 완료. 사업 성공을 의미하지 않습니다.'
    def test_all_tables(self):
        with office.db() as c:
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue(set(['projects','tasks','runs','evidence','memories','decisions','human_requests','events','artifacts','improvements'])<=tables)
    def test_ready_default(self): self.assertEqual(self.status(self.task()),'READY')
    def test_no_invalid_role(self):
        with self.assertRaises(ValueError): office.add('x','y',role='ROOT')
    def test_dependency_wait(self):
        a=self.task(); b=office.add('b','b',dependencies=[a]); self.assertIsNone(office.run_task(b)); self.assertEqual(self.status(b),'WAITING_EXTERNAL')
    def test_unknown_dependency(self):
        with self.assertRaises(ValueError): office.add('b','b',dependencies=['no'])
    def test_korean_spacing(self):
        office.memory('시장 검증과 고객 확보 전략',tags='창업')
        self.assertEqual(len(office.search('시장검증')),1)
    def test_korean_synonym(self):
        office.memory('고객 확보 전략')
        self.assertEqual(len(office.search('고객유치')),1)
    def test_search_quotes_safe(self): self.assertEqual(office.search('" OR *'),[])
    def test_env_api_removed(self):
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'test','OPENAI_API_KEY':'test','ANTHROPIC_BASE_URL':'test'}):
            self.assertNotIn('ANTHROPIC_API_KEY',office.clean_env()); self.assertNotIn('OPENAI_API_KEY',office.clean_env())
    def test_failure_classes(self):
        for text,status in [('usage limit','WAITING_QUOTA'),('authentication failed','NEEDS_LOGIN'),('sandbox denied','BLOCKED'),('bad result','FAILED')]:
            self.assertEqual(office.failure_status(text),status)
    def test_validation_unknown_source(self): self.assertTrue(office.validate(self.text()+'[E:aaaaaaaaaaaaaaaa]',[],[]))
    def test_validation_requires_evidence(self): self.assertTrue(office.validate(self.text(),[],['aaaaaaaaaaaaaaaa']))
    def test_validation_missing_section(self): self.assertTrue(office.validate(self.text(),['不存在'],[]))
    def test_complete_with_artifact(self):
        t=self.task()
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.text()}): self.assertEqual(office.run_task(t),'DONE')
        with office.db() as c: self.assertEqual(c.execute('SELECT verified FROM artifacts').fetchone()[0],1)
    def test_failed_review_never_done(self):
        t=self.task(True)
        with patch('office.invoke',side_effect=[{'status':'COMPLETED','text':self.text()},{'status':'COMPLETED','text':'{"verdict":"REVISE","issues":["bad"],"reason":"bad"}'}]):
            self.assertEqual(office.run_task(t),'REVIEW')
        self.assertEqual(self.status(t),'REVIEW')
    def test_review_gate_pass(self):
        t=self.task(True)
        with patch('office.invoke',side_effect=[{'status':'COMPLETED','text':self.text()},{'status':'COMPLETED','text':'{"verdict":"PASS","issues":[],"reason":"OK"}'}]): self.assertEqual(office.run_task(t),'DONE')
    def test_quota_wait(self):
        t=self.task()
        with patch('office.invoke',return_value={'status':'WAITING_QUOTA','text':'usage limit'}): self.assertEqual(office.run_task(t),'WAITING_QUOTA')
        with self.assertRaises(ValueError): office.run_task(t)
    def test_done_no_duplicate(self):
        t=self.task()
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.text()}): office.run_task(t)
        with self.assertRaises(ValueError): office.run_task(t)
    def test_recovery_no_blind_retry(self):
        t=self.task()
        with office.db() as c: office.state(c,t,'RUNNING')
        office.recover(); self.assertEqual(self.status(t),'WAITING_EXTERNAL')
    def test_revision_limit(self):
        t=self.task()
        for _ in range(2):
            with office.db() as c: office.state(c,t,'REVIEW')
            office.retry(t)
        with office.db() as c: office.state(c,t,'REVIEW')
        with self.assertRaises(ValueError): office.retry(t)
    def test_stop(self):
        t=self.task(); (office.ROOT/'data/STOP').touch()
        with self.assertRaises(RuntimeError): office.run_task(t)
    def test_backup_restore(self):
        t=self.task(); archive=office.backup(); dest=office.ROOT/'restore'
        office.restore_copy(archive,dest)
        with sqlite3.connect(dest/'data/office.sqlite3',factory=office.ClosingConnection) as c: self.assertEqual(c.execute('SELECT id FROM tasks').fetchone()[0],t)
    def test_unsafe_archive(self):
        z=office.ROOT/'bad.zip'
        with zipfile.ZipFile(z,'w') as f: f.writestr('../escape','no')
        with self.assertRaises(ValueError): office.restore_copy(z,office.ROOT/'restore')
    def test_no_restore_overwrite(self):
        with self.assertRaises(ValueError): office.restore_copy(office.backup(),office.ROOT)
    def test_lock_exclusion(self):
        with office.lock():
            with self.assertRaises(RuntimeError):
                with office.lock(): pass
    def test_dashboard_escapes(self):
        office.add('<script>alert(1)</script>','x'); self.assertNotIn('<script>',office.dashboard())
    def test_daily_disabled_no_model(self):
        with patch('office.invoke') as call: office.daily(); call.assert_not_called()
    def test_daily_idempotent(self):
        cfg=office.config(); cfg['automatic_execution']=True; office.dump(office.ROOT/'config.json',cfg)
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.text()}) as call:
            self.assertEqual(office.daily(),'DONE'); self.assertEqual(office.daily(),'ALREADY_CLAIMED'); self.assertEqual(call.call_count,1)
    def test_daily_quota_blocks(self):
        cfg=office.config(); cfg['automatic_execution']=True; office.dump(office.ROOT/'config.json',cfg)
        t=self.task()
        with office.db() as c: office.state(c,t,'WAITING_QUOTA')
        with patch('office.invoke') as call: self.assertEqual(office.daily(),'WAITING'); call.assert_not_called()
    def test_review_quota_resume_reuses_draft(self):
        t=self.task(True)
        with patch('office.invoke',side_effect=[{'status':'COMPLETED','text':self.text()},{'status':'WAITING_QUOTA','text':'usage limit'}]) as call:
            self.assertEqual(office.run_task(t),'WAITING_QUOTA'); self.assertEqual(call.call_count,2)
        office.retry(t)
        with patch('office.invoke',return_value={'status':'COMPLETED','text':'{"verdict":"PASS","issues":[],"reason":"OK"}'}) as call:
            self.assertEqual(office.run_task(t),'DONE'); self.assertEqual(call.call_count,1)
    def test_malformed_review_not_done(self):
        t=self.task(True)
        with patch('office.invoke',side_effect=[{'status':'COMPLETED','text':self.text()},{'status':'COMPLETED','text':'looks fine'}]):
            self.assertEqual(office.run_task(t),'REVIEW')
    def test_restore_detects_modified_artifact(self):
        t=self.task()
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.text()}): office.run_task(t)
        with office.db() as c: artifact=c.execute('SELECT path FROM artifacts').fetchone()[0]
        (office.ROOT/artifact).write_text('modified',encoding='utf-8')
        with self.assertRaises(ValueError): office.restore_copy(office.backup(),office.ROOT/'restore')

if __name__=='__main__': unittest.main()
