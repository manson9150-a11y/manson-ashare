from copy import deepcopy
from datetime import datetime
import pytest
from src.research.stocks import history_candidates, select, price_plan, attach, catalyst_analysis, tracking_seed
from src.catalysts.evidence import verify_text
from src.utils.calendar import TZ


def stock(**updates):
    s={'stock_code':'600001','stock_name':'测试','price':11.,'ma10':10.5,'ma20':10.,'atr':.5,'bars_count':65,
       'timestamp':'2026-09-11T15:00:00+08:00','return_5d':5.,'return_20d':10.,'distance_ma20':10.,
       'natr':4.,'amount_ratio_5d':1.2,'position_type':'趋势观察','hard_risk':False,'independent_catalyst':False,
       'pool':'POOL_B','bars':[{'high':12.} for _ in range(25)],'events':[]}
    s.update(updates);return s


def run(**updates):
    r={'run_id':'r','stage':'2200','quote_date':'2026-09-11','as_of_time':'2026-09-11T22:00:00+08:00','pools':{'POOL_B':[stock()]}}
    r.update(updates);return r


def test_discovery_includes_unmapped_movers_without_exceeding_budget(quote,config):
    config=deepcopy(config);config['sources']['max_history_stocks']=5
    rows=[quote.model_copy(update={'code':f'60000{i}','change_pct':i+1,'amount':1e8*(10-i),'turnover':i,'limit_up_price':None}) for i in range(9)]
    rows.append(quote.model_copy(update={'code':'600099','name':'ST测试','change_pct':20,'amount':1e10}))
    picked=history_candidates(rows,set(),set(),config)
    assert len(picked)==5 and len({q.code for q in picked})==5
    assert '600008' in {q.code for q in picked} and '600099' not in {q.code for q in picked}


def test_ladder_retired_and_volatile_catalyst_remains_labeled(config):
    b=stock(is_limit_up=True)
    h=stock(stock_code='600002',return_5d=30,independent_catalyst=True)
    picked,_=select([b,h],'2200',config)
    assert not picked['POOL_A'] and picked['POOL_B'][0]['stock_code']=='600001'
    assert picked['POOL_H'][0]['independent_catalyst'] and picked['POOL_H'][0]['observation_only']
    for stage in ['0800','1200']:
        again,_=select([b,h],stage,config,{'pools':picked})
        assert again['POOL_H'][0]['stock_code']=='600002'


def test_valid_plan_has_ordered_conditional_levels(config):
    p=price_plan(stock(),run(),config)
    assert 0<p['invalidation_price']<p['entry_zone'][0]<p['entry_zone'][1]<p['resistance_reference']
    assert p['reward_risk_to_resistance']>0 and '确认' in p['trigger']


@pytest.mark.parametrize('changes',[{'atr':None},{'ma10':float('nan')},{'bars_count':20},{'amount_ratio_5d':None},
    {'timestamp':'2026-09-12T15:00:00+08:00'},{'timestamp':'2026-09-10T15:00:00+08:00'},{'pool':'POOL_H'},{'hard_risk':True}])
def test_missing_future_stale_or_volatile_data_cannot_make_entry_plan(config,changes):
    assert price_plan(stock(**changes),run(),config)['entry_zone'] is None


def test_no_intraday_volume_comparison_no_price_plan(config):
    p=price_plan(stock(amount_ratio_5d=None,timestamp='2026-09-11T11:30:00+08:00'),run(stage='1200',as_of_time='2026-09-11T12:00:00+08:00'),config)
    assert p['status']=='WAIT_CONFIRMATION' and p['entry_zone'] is None


def test_broken_previous_stop_is_not_silently_lowered(config):
    old=run(run_id='previous',pools={'POOL_B':[stock(price=12,research={'price_plan':{'invalidation_price':11.5}})]})
    current=attach(run(),config,old)
    r=current['pools']['POOL_B'][0]['research']
    assert r['change']['label']=='前次条件已失效'
    assert r['price_plan']['status']=='INVALIDATED' and r['price_plan']['entry_zone'] is None


def test_pdf_general_termination_clause_is_not_actual_termination(event):
    e=event.model_copy(update={'stock_code':'600001','title':'关于签订销售合同的公告','verified':False})
    text='证券代码600001。公司签订销售合同。合同对到货验收、解除条款等进行了明确约定。合同金额占公司2025年度营业收入的25%。'
    result=verify_text(e,text,datetime(2026,9,11,22,tzinfo=TZ))
    assert result.verified
    assert result.verification['contract_status']=='SIGNED_DISCLOSED'


def test_contract_reduction_precedes_positive_materiality(event):
    e=event.model_copy(update={'stock_code':'600001','title':'重大合同进展公告','verified':False})
    text='证券代码600001。公司签订补充合同。合同金额下调至3亿元，占公司2025年度营业收入的20%。'
    result=verify_text(e,text,datetime(2026,9,11,22,tzinfo=TZ))
    assert not result.verified and result.impact_score is None
    assert result.verification['business_direction']=='NEGATIVE_REVISION'
    assert catalyst_analysis([result.model_dump()])['status']=='RISK'


def test_unparsed_does_not_invent_unsigned_contract():
    r=catalyst_analysis([{'event_id':'e','title':'重大合同进展','verified':False,'verification':{'reason':'CONTRACT_NOT_CONFIRMED'}}])
    assert '未签署' not in r['conclusion']
    assert '不能据标题' in r['conclusion']


def test_null_verification_is_supported():
    assert catalyst_analysis([{'event_id':'e','verification':None}])['status']=='UNCONFIRMED'


def test_posthoc_seed_is_only_usable_in_a_later_matching_run():
    previous=run();seed={'base_run_id':'r','quote_date':'2026-09-11','generated_at':'2026-09-12T00:00:00+08:00',
        'pools':{'POOL_H':[stock(pool='POOL_H')]},'quotes':[{'timestamp':'2026-09-11T15:00:00+08:00'}],'factors':{'600001':{}},'stock_research':{}}
    future=datetime(2026,9,14,8,tzinfo=TZ)
    assert tracking_seed(previous,seed,future)['pools']['POOL_H']
    assert tracking_seed(previous,seed,datetime(2026,9,11,23,tzinfo=TZ)) is previous
    assert tracking_seed(previous,{**seed,'base_run_id':'other'},future) is previous


def test_routine_meeting_is_not_described_as_an_order():
    result=catalyst_analysis([{'event_id':'e','title':'关于召开业绩说明会的公告','verification':None}])
    assert result['status']=='ROUTINE' and '例行' in result['headline']
    assert '签约' not in result['next_check']


def test_h_observations_keep_quotes_and_factors_through_three_stages(tmp_path,config):
    from pathlib import Path
    from datetime import date
    from src.pipeline import Pipeline
    config=deepcopy(config);config['stock_research']['hot_return_5d']=0
    pipeline=Pipeline(Path(__file__).parents[1],tmp_path,'demo',config)
    for day,stage in [(date(2026,9,3),'2200'),(date(2026,9,4),'0800'),(date(2026,9,4),'1200')]:
        result=pipeline.run(day,stage)
        assert result['status']=='COMPLETE'
        h=result['pools']['POOL_H'];assert h
        codes={s['stock_code'] for s in h}
        assert codes <= {q['code'] for q in result['quotes']}
        assert codes <= set(result['factors'])
        assert all(s['research']['price_plan']['entry_zone'] is None for s in h)
