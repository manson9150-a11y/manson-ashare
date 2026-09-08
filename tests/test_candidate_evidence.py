from datetime import date, datetime
import copy
import httpx
import pytest
from src.collectors.base import Unavailable
from src.collectors.public import EastmoneyAdapter
from src.collectors.limit_evidence import upper_price, rate_for, enrich_limits
from src.catalysts.evidence import verify_text
from src.catalysts.engine import expectation, independent
from src.screening.pools import pools
from src.utils.calendar import TZ, TradingCalendar
from pathlib import Path
from decimal import Decimal


def test_missing_limit_payload_fails_instead_of_successful_zero(config):
    a=EastmoneyAdapter(config)
    a.client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'data':None})))
    with pytest.raises(Unavailable): a.fetch('limit_pool',day=date(2026,9,7))


def test_limit_pool_normalizes_vendor_price(config):
    def handler(request):
        assert request.url.params['ut']=='7eea3edcaed734bea9cbfc24409ed989'
        return httpx.Response(200,json={'data':{'qdate':20260907,'pool':[{'c':'600001','p':11000,'lbc':2}]}})
    a=EastmoneyAdapter(config);a.client=httpx.Client(transport=httpx.MockTransport(handler))
    assert a.fetch('limit_pool',day=date(2026,9,7))[0]['limit_up_price']==11


def test_rounding_is_half_up_and_exceptions_stay_unknown(quote):
    assert upper_price(10.05,Decimal('.10'))==11.06
    assert rate_for(quote.model_copy(update={'name':'C新股'})) is None
    assert rate_for(quote.model_copy(update={'name':'*ST测试'})) is None
    assert rate_for(quote.model_copy(update={'code':'920001'})) is None


def sample_limit(quote):
    calendar=TradingCalendar(Path(__file__).parents[1]/'config/calendar.json')
    dates=calendar.sessions(date(2026,5,1),date(2026,9,7))[-65:]
    bars=[{'timestamp':str(d)+'T15:00:00+08:00','close':10.,'high':10.,'low':10.,'volume':100} for d in dates]
    bars[-1].update(close=11.,high=11.)
    q=quote.model_copy(update={'code':'600001','name':'测试公司','price':11.,'previous_close':10.,'high':11.,'low':10.,'limit_up_price':None,'timestamp':datetime(2026,9,7,15,tzinfo=TZ)})
    return q,{'600001':{'bars':bars}},calendar


def test_sina_like_quote_has_auditable_limit_fallback(quote):
    q,f,c=sample_limit(quote)
    rows,status=enrich_limits([q],f,[],date(2026,9,7),c)
    assert len(rows)==1 and rows[0]['derived_board_count']==1
    assert rows[0]['board_count'] is None
    assert rows[0]['identity_basis']=='rule_derived_not_vendor_confirmed'
    assert status['rule_derived']==1


@pytest.mark.parametrize('case',['opened','new_listing','ex_rights','gap','over_limit'])
def test_inference_does_not_invent_limit_identity(quote,case):
    q,f,c=sample_limit(quote)
    if case=='opened': q=q.model_copy(update={'price':10.8});f['600001']['bars'][-1]['close']=10.8
    if case=='new_listing': f['600001']['bars']=f['600001']['bars'][-4:]
    if case=='ex_rights': q=q.model_copy(update={'previous_close':9.5})
    if case=='gap': f['600001']['bars'][-1]['timestamp']='2026-09-04T15:00:00+08:00'
    if case=='over_limit':q=q.model_copy(update={'high':12.})
    rows,_=enrich_limits([q],f,[],date(2026,9,7),c)
    assert rows==[]


def test_stale_or_opened_vendor_pool_is_rejected(quote):
    q,f,c=sample_limit(quote);q=q.model_copy(update={'price':10.8})
    rows,status=enrich_limits([q],{},[{'code':q.code,'trade_date':'2026-09-07','limit_up_price':11.,'board_count':4}],date(2026,9,7),c)
    assert not rows and status['rejected_vendor_rows']==[q.code]


@pytest.fixture
def contract(event):
    return event.model_copy(update={'stock_code':'600001','title':'关于签订重大合同的公告',
        'verified':False,'impact_score':None,'document_url':'https://static.cninfo.com.cn/finalpage/2026-09-03/123.PDF'})


def test_material_contract_requires_body_identity_and_facts(contract,config):
    text='证券代码：600001 公司近日签订销售合同。本次合同金额占公司2025年度营业收入的25%。'
    e=verify_text(contract,text,datetime(2026,9,4,8,tzinfo=TZ))
    assert e.verified and e.impact_score==80
    assert e.verification['rule']=='SIGNED_CONTRACT_REVENUE_10PCT'
    assert independent(expectation([e],{},datetime(2026,9,4,8,30,tzinfo=TZ),config)[0],config)


@pytest.mark.parametrize('text',[
    '证券代码：600002 公司签订销售合同。合同金额占公司2025年度营业收入的25%。',
    '证券代码：600001 公司尚未签订销售合同。合同金额占公司2025年度营业收入的25%。',
    '证券代码：600001 公司签订销售合同。合同金额占公司2025年度营业收入的2%。',
    '证券代码：600001 公司签订销售合同。合同金额占公司2025年半年度营业收入的25%。',
    '证券代码：600001 公司签订销售合同，预计业务前景良好。',
    '证券代码：600001 公司签订销售合同。合同金额占公司2025年度营业收入的25%。该合同已经终止。',
])
def test_title_or_ambiguous_contract_does_not_earn_verified_score(contract,text):
    e=verify_text(contract,text,datetime(2026,9,4,8,tzinfo=TZ))
    assert not e.verified and e.impact_score is None


def test_profit_forecast_positive_and_growth_lower_bound(contract):
    e=contract.model_copy(update={'title':'2026年前三季度业绩预告'})
    text='证券代码：600001 归属于上市公司股东的净利润盈利：1000万元至1500万元，比上年同期增长：60%至90%。'
    r=verify_text(e,text,datetime(2026,9,4,8,tzinfo=TZ))
    assert r.verified and r.impact_score==70
    assert not verify_text(e,text.replace('60%','20%'),datetime(2026,9,4,8,tzinfo=TZ)).verified
    assert not verify_text(e,text.replace('盈利：1000','亏损：1000'),datetime(2026,9,4,8,tzinfo=TZ)).verified


def test_new_verified_catalyst_can_enter_c_after_close_but_not_midday(config):
    s={'stock_code':'600001','position_type':'趋势观察','total_score':80,'is_limit_up':False,'independent_catalyst':True}
    previous={'pools':{'POOL_A':[],'POOL_B':[],'POOL_C':[]}}
    selected,_=pools([s],'2130',config,previous)
    assert selected['POOL_C'][0]['stock_code']=='600001'
    selected,_=pools([s],'1135',config,previous)
    assert not any(selected.values())
    s['independent_catalyst']=False
    selected,_=pools([s],'2130',config,previous)
    assert not any(selected.values())


def test_effective_large_sales_contract_is_not_confused_with_spending(contract):
    text='证券代码：600001 合同已正式签署并生效。上述销售合同为公司日常经营合同。合同含税金额为118,841.88万元人民币。本协议租赁期限为60个月。'
    e=verify_text(contract,text,datetime(2026,9,4,8,tzinfo=TZ))
    assert e.verified and e.verification['contract_amount_yuan']==1188418800
    assert e.verification['contract_duration']=='租赁期限为60个月'
    assert not verify_text(contract,text.replace('销售合同','采购合同'),datetime(2026,9,4,8,tzinfo=TZ)).verified
    assert not verify_text(contract,text.replace('已正式签署并生效','尚未生效'),datetime(2026,9,4,8,tzinfo=TZ)).verified


@pytest.mark.parametrize('payload',[
    {'data':{'qdate':20260904,'pool':[{'c':'600001','p':11000}]}},
    {'data':{'qdate':20260907,'tc':3,'pool':[{'c':'600001','p':11000}]}},
])
def test_stale_and_truncated_limit_pools_fail(config,payload):
    a=EastmoneyAdapter(config)
    a.client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload)))
    with pytest.raises(Unavailable): a.fetch('limit_pool',day=date(2026,9,7))


def test_live_pipeline_discovers_c_without_trend_membership(tmp_path,config,monkeypatch):
    from src.pipeline import Pipeline
    from src.collectors.demo import DemoData
    from src.catalysts.evidence import CatalystEvidence
    root=Path(__file__).parents[1]
    as_of=datetime(2026,9,4,16,tzinfo=TZ)
    pipeline=Pipeline(root,tmp_path,'live',config)
    sample=DemoData(pipeline.calendar,as_of,'1600')
    config['wudao']['enabled']=False
    config['catalyst_evidence']['enabled']=True
    config['sources']['expected_universe_min']=80
    event=sample.events()[0]
    def discover(self, cutoff):
        self.status['discovered']=1
        return [event]
    monkeypatch.setattr(CatalystEvidence,'discover',discover)
    monkeypatch.setattr(pipeline.announcements,'fetch',lambda *a,**kw:[])
    members=copy.deepcopy(sample.membership)
    for group in members: group['codes']=[c for c in group['codes'] if c!=event.stock_code]
    monkeypatch.setattr(pipeline,'membership',lambda *a:members)
    def fetch(operation,**kwargs):
        if operation=='universe':return sample.universe
        if operation=='quotes':return sample.quotes
        if operation=='history':return sample.frames[kwargs['code']]
        if operation=='limit_pool':raise Unavailable('empty')
        raise AssertionError(operation)
    monkeypatch.setattr(pipeline.collector,'fetch',fetch)
    monkeypatch.delenv('GOOGLE_DOC_ID',raising=False)
    run=pipeline.run(date(2026,9,4),'1600',as_of)
    assert run['status']=='COMPLETE',run['errors']
    assert any(s['stock_code']==event.stock_code for s in run['pools']['POOL_C'])
    assert run['catalyst_evidence']['verified']==1
    assert 'POOL_A' in run['pool_diagnostics']
