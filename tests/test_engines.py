from datetime import datetime,timedelta
import pytest
from src.market.engine import market_score
from src.sectors.engine import sector_scores
from src.risk.position import classify
from src.catalysts.engine import deduplicate,expectation,independent
from src.utils.calendar import TZ
from src.screening.pools import pools

def test_market_score_bounds_and_config(quote,config):
    m=market_score([quote],config,{'status':'GREEN'})
    assert 70<=m['score']<=100 and m['environment']=='强'
    config['market']['strong_threshold']=101
    assert market_score([quote],config,{'status':'GREEN'})['environment']=='正常'
    assert market_score([quote],config,{'status':'RED'})['score'] is None

def test_sector_diffusion_over_one_leader(quote,config):
    down=[quote.model_copy(update={'code':f'{600002+i}','change_pct':-1.,'amount':100000000}) for i in range(9)]
    members=[{'id':'x','name':'test','kind':'concept','codes':[q.code for q in [quote]+down]}]
    result=sector_scores([quote]+down,members,{},config)[0]
    assert result['breadth']==.1 and result['score']<45 and result['return_5d'] is None

@pytest.fixture
def f():return {'ma20':10,'slope_ma20':.2,'return_5d':5,'return_20d':10,'distance_ma20':5,'move_atr':1,'amount_ratio_5d':1.3,'bull_alignment':True,'breakout':True}
@pytest.mark.parametrize('change,expected',[({},'启动观察'),({'breakout':False},'趋势观察'),({'return_20d':50},'高位观察'),({'return_5d':-2,'amount_ratio_5d':.7},'回调观察'),({'slope_ma20':-1},'排除'),({'ma20':None},'排除'),({'move_atr':3.1},'高位观察')])
def test_classification(f,config,change,expected):
    f.update(change);assert classify(f,{'state':'正在加强'},config)[0]==expected

def test_hard_risk(f,config):assert classify(f,{'state':'正在加强'},config,True)[0]=='排除'

def test_event_dedup_and_future(event):
    now=datetime(2026,9,4,8,30,tzinfo=TZ)
    copy=event.model_copy(update={'event_id':'2','source':'media','reliability':.6})
    future=event.model_copy(update={'event_id':'3','title':'different','publish_time':now+timedelta(hours=1)})
    assert deduplicate([copy,event,future],now)==[event]

def test_canonical_id_syndication(event):
    a=event.model_copy(update={'canonical_id':'official-document-1'})
    b=event.model_copy(update={'canonical_id':'official-document-1','title':'转发：合同新标题','reliability':.5})
    assert len(deduplicate([a,b],datetime(2026,9,4,8,30,tzinfo=TZ)))==1

def test_expectation_and_unverified_catalyst(event,config):
    rows=expectation([event],{'600001':{'return_20d':45}},datetime(2026,9,4,8,30,tzinfo=TZ),config)
    assert rows[0]['expectation']=='Overpriced'
    assert independent(rows[0],config)
    rows[0]['verified']=False
    assert not independent(rows[0],config)

def test_pool_no_new_candidates(config):
    s={'stock_code':'600001','position_type':'趋势观察','total_score':80,'is_limit_up':False,'independent_catalyst':False}
    result,_=pools([s],'0830',config,{'pools':{'POOL_B':[]}})
    assert not any(result.values())
