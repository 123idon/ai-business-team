import json,unittest
from unittest.mock import patch
import office,team,advisor,desk,test_office

class AdvisorTests(unittest.TestCase):
    setUp=test_office.OfficeTests.setUp
    tearDown=test_office.OfficeTests.tearDown
    def answer(self,**overrides):
        proposal=dict(mode='single',agent_id='baek_marketing',title='콘텐츠 방향',brief='실제 상품 정보가 제공되기 전에는 기획 양식만 만들고 미확인 항목은 빈칸으로 남긴다.',reason='상품 정보를 먼저 정리해야 초안을 만들 수 있습니다.',materials=['상품 설명'])
        proposal.update(overrides)
        return '# 추천\n마케팅 전략 직원에게 기획을 맡겨보세요.\n# 이유\n조건을 먼저 정리해야 초안을 만들 수 있습니다.\n# 준비 자료\n상품 설명이 필요합니다. 자료가 없으면 양식 작성부터 맡기세요.\n# 지시문\n실제 정보와 미확인 항목을 구분한 기획 카드를 만들어 주세요. 상담으로 실제 배정되지는 않았습니다.\n```advisor-plan\n'+json.dumps({'proposals':[proposal]},ensure_ascii=False)+'\n```'
    def test_recommendation_does_not_dispatch(self):
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.answer()}): advisor.ask('baek','무엇을 맡길까?')
        with office.db() as c:
            rows=c.execute('SELECT * FROM tasks').fetchall()
            self.assertEqual(len(rows),1); self.assertEqual(rows[0]['task_kind'],'advice'); self.assertEqual(rows[0]['status'],'DONE')
        self.assertEqual(advisor.latest('baek')[0]['proposals'][0]['agent_id'],'baek_marketing')
        self.assertEqual(advisor.latest('startup'),[])
    def test_cross_office_and_modes_rejected(self):
        for change in [dict(agent_id='startup_strategy'),dict(mode='shell'),dict(mode='orders'),dict(mode='team'),dict(agent_id='baek_advisor')]:
            with self.assertRaises(ValueError): advisor.parse(self.answer(**change),'baek')
    def test_local_order_route(self):
        result=advisor.parse(self.answer(mode='orders',agent_id='baek_orders'),'baek')
        self.assertEqual(result[0]['mode'],'orders')
    def test_advisor_not_auto_assigned(self):
        text='```office-actions\n'+json.dumps({'actions':[{'agent_id':'baek_advisor','title':'상담','brief':'추천','kind':'document'}]})+'\n```'
        with self.assertRaises(ValueError): team.parse_actions(text,'baek')
    def test_invalid_advice_never_done(self):
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.answer(agent_id='startup_strategy')}): advisor.ask('baek','도와줘')
        with office.db() as c: self.assertEqual(c.execute('SELECT status FROM tasks').fetchone()[0],'REVIEW')
        self.assertEqual(advisor.latest('baek'),[])
    def test_office_context_separation(self):
        team.assign('startup_strategy','PRIVATE_STARTUP_TOPIC','brief')
        self.assertNotIn('PRIVATE_STARTUP_TOPIC',advisor.prompt('baek','내 할 일을 추천해줘'))
    def test_editable_safe_handoff_ui(self):
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.answer(title='<script>x</script>')}): advisor.ask('baek','조언해줘')
        page=desk.render('baek','token')
        self.assertIn('조언과 지시문 추천받기',page); self.assertIn('이 지시문으로 직원에게 배정',page)
        self.assertIn('&lt;script&gt;',page); self.assertNotIn('<script>x</script>',page)
        self.assertIn('id="orders"',page)
    def test_result_hash_checked(self):
        with patch('office.invoke',return_value={'status':'COMPLETED','text':self.answer()}): advisor.ask('baek','추천해줘')
        with office.db() as c: a=c.execute('SELECT * FROM artifacts').fetchone()
        (office.ROOT/a['path']).write_text('altered',encoding='utf-8')
        self.assertEqual(advisor.latest('baek'),[])
