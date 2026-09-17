import json,unittest
from unittest.mock import patch
import office,team,meetings,briefings,desk,test_office

class BriefingTests(unittest.TestCase):
    setUp=test_office.OfficeTests.setUp
    tearDown=test_office.OfficeTests.tearDown
    def source(self,project='baek',title='실제 원본 결과'):
        tid=team.assign(project+'_chief',title,'입력',important=False)
        with patch('office.invoke',return_value={'status':'COMPLETED','text':test_office.OfficeTests.text(self)}): office.run_task(tid)
        return tid
    def report(self):
        return '# 핵심 결론\n제공된 가설을 정리했고 외부 검증은 아직 하지 않았습니다.\n# 업무별 결과\n직원은 고객 확보 실험 양식을 작성했습니다.\n# 의견 차이와 미확인\n고객 수요는 아직 미확인입니다.\n# 대표님이 결정할 사항\n검증할 고객군을 알려주세요.\n# 다음 할 일\n담당 실장이 자료를 받아 검증 질문을 보완하도록 제안합니다. 아직 새 업무를 배정하지 않았습니다.\n완료 기준: 원문 내용을 종합했으며 사실 검증은 미완료입니다.'
    def replies(self): return [{'status':'COMPLETED','text':self.report()},{'status':'COMPLETED','text':'{"verdict":"PASS","issues":[],"reason":"원문과 부합"}'}]
    def test_verified_sources_scoped_and_no_drafts(self):
        good=self.source(); self.source('startup','PRIVATE_STARTUP')
        pending=team.assign('baek_chief','아직 미완료','no data',important=False)
        tid=briefings.ensure('baek')
        with office.db() as c: t=dict(c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone())
        self.assertIn(good,t['prompt']); self.assertIn(pending,t['prompt'])
        self.assertNotIn('PRIVATE_STARTUP',t['prompt']); self.assertEqual(t['owner_agent'],'baek_chief')
        self.assertEqual([d['task'] for d in briefings.sources('baek')['results']],[good])
    def test_report_dedup_no_recursion_and_new_results(self):
        self.source()
        with patch('office.invoke',side_effect=self.replies()) as model:
            tid=briefings.refresh('baek'); self.assertEqual(briefings.refresh('baek'),tid)
            self.assertEqual(model.call_count,2)
        self.assertIn('고객 확보',briefings.panel('baek'))
        self.assertNotIn('이 보고 이후',briefings.panel('baek'))
        self.source(title='새 결과')
        self.assertIn('이 보고 이후',briefings.panel('baek'))
        self.assertNotEqual(briefings.ensure('baek'),tid)
        with office.db() as c: self.assertEqual(c.execute('SELECT count(*) FROM campaigns').fetchone()[0],0)
    def test_automatic_batch_report_and_no_infinite_loop(self):
        cfg=office.config(); cfg['chief_briefings']=True; office.dump(office.ROOT/'config.json',cfg)
        tid=team.assign('baek_chief','자동 보고 대상','입력',important=False)
        with patch('office.invoke',side_effect=[{'status':'COMPLETED','text':test_office.OfficeTests.text(self)}]+self.replies()) as model:
            meetings.run_turns([tid]); self.assertEqual(model.call_count,3)
        with office.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],2)
            self.assertEqual(c.execute("SELECT status FROM tasks WHERE task_kind='briefing'").fetchone()[0],'DONE')
    def test_tampered_source_excluded_and_report_not_displayed(self):
        tid=self.source(); a,_=briefings.artifact(tid)
        (office.ROOT/a['path']).write_text('tampered',encoding='utf-8')
        data=briefings.sources('baek'); self.assertEqual(data['results'],[])
        self.assertIn('result_error',data['tasks'][0]); self.assertIsNone(briefings.ensure('baek'))
    def test_html_escape_and_top_level_report(self):
        markup=briefings.rich_text('# 결론\n<script>bad</script>\n**강조**')
        self.assertNotIn('<script>',markup); self.assertIn('<strong>강조</strong>',markup)
        page=desk.render('baek','token')
        self.assertLess(page.index('id="chief-report"'),page.index('id="meeting"'))
        self.assertIn('<details><summary>개별 업무',page)
        self.assertIn('live-chief-report',desk.render('baek','token',fragments=True))
    def test_orders_only_safe_counts(self):
        tid=office.add('주문지 로컬 정리','입력',project='baek',owner_agent='baek_orders',task_kind='local_orders',important=False)
        with office.db() as c: office.state(c,tid,'DONE',json.dumps({'rows':8,'flagged':2,'customer':'PRIVATE_CUSTOMER'}))
        data=briefings.sources('baek')
        self.assertIn('8행',data['results'][0]['text']); self.assertNotIn('PRIVATE_CUSTOMER',json.dumps(data))
        self.assertIsNotNone(briefings.ensure('baek'))
    def test_report_integrity_before_display(self):
        self.source()
        with patch('office.invoke',side_effect=self.replies()): tid=briefings.refresh('baek')
        a,_=briefings.artifact(tid); (office.ROOT/a['path']).write_text('TAMPERED_REPORT',encoding='utf-8')
        panel=briefings.panel('baek')
        self.assertNotIn('TAMPERED_REPORT',panel); self.assertIn('파일을 확인할 수 없습니다',panel)
