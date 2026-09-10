from datetime import date, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from src.collectors.base import Collector, Unavailable
from src.collectors.market_history import HistoryStore, build_market_context
from src.collectors.baostock import BaoStockAdapter
from src.collectors.public import sina_daily_frame
from src.utils.calendar import TZ, TradingCalendar
from src.utils.io import write_json

class FrameSource:
    def __init__(self, config, frame, name, priority):
        self.config=config;self.frame=frame;self.source_name=name;self.fallback_priority=priority;self.reliability_level=.8;self.calls=0
    def fetch(self, operation, **kwargs):
        self.calls+=1
        return self.frame.assign(source=self.source_name)

def test_price_only_source_does_not_block_amount_fallback(tmp_path,config,bars):
    poor=FrameSource(config,bars.assign(amount=None),'price_only',0)
    full=FrameSource(config,bars,'complete',1)
    collector=Collector([poor,full]);store=HistoryStore(tmp_path,collector,config)
    end=bars.timestamp.iloc[-1].date();now=bars.timestamp.iloc[-1]+timedelta(hours=7)
    result=store.fetch('600001',end,now)
    assert result.source.iloc[-1]=='complete' and result.amount.notna().all()
    assert poor.calls==full.calls==1
    store.fetch('600001',end,now)
    assert full.calls==1

def test_partial_amount_remains_null_and_stale_history_rejected(tmp_path,config,bars):
    source=FrameSource(config,bars.assign(amount=None),'partial',0)
    store=HistoryStore(tmp_path,Collector([source]),config)
    end=bars.timestamp.iloc[-1].date();now=bars.timestamp.iloc[-1]+timedelta(hours=7)
    frame=store.fetch('600001',end,now)
    assert frame.amount.isna().all()
    with pytest.raises(Unavailable):store.fetch('600001',end+timedelta(days=1),now+timedelta(days=1))

def test_cache_never_reads_later_observation(tmp_path,config,bars):
    source=FrameSource(config,bars,'fixture',0);store=HistoryStore(tmp_path,Collector([source]),config)
    end=bars.timestamp.iloc[-1].date();now=bars.timestamp.iloc[-1]+timedelta(hours=7)
    store.fetch('600001',end,now)
    store.fetch('600001',end,now-timedelta(hours=1))
    assert source.calls==2

@pytest.mark.parametrize('text',['var KLC_K2_sh600001="abc";', 'globalThis.process.exit();','var KLC_K2_sh600000="x!";'])
def test_sina_payload_strict_symbol_and_data_only(text):
    with pytest.raises(Unavailable):sina_daily_frame(text,'600000',date(2026,9,9),100)

def test_baostock_keeps_supplied_currency_amount(config,monkeypatch):
    row=dict(date='2026-09-09',code='sh.600000',open='9.25',high='9.29',low='9.21',close='9.23',volume='50532458',amount='467549947.30',adjustflag='3')
    monkeypatch.setattr('src.collectors.baostock.subprocess.run',lambda *a,**k:SimpleNamespace(stdout=json.dumps({'rows':[row]})))
    frame=BaoStockAdapter(config).fetch('history',code='600000',end=date(2026,9,9))
    assert frame.amount.iloc[-1]==467549947.3 and frame.volume.iloc[-1]==50532458
    row['adjustflag']='2'
    with pytest.raises(Unavailable):BaoStockAdapter(config).fetch('history',code='600000',end=date(2026,9,9))

class ContextCollector:
    def __init__(self, day, count=2):
        self.logs=[{'operation':'limit_pool','success':True,'source_name':'eastmoney','timestamp':str(day),'count':count}]
    def fetch(self, operation, **kwargs):
        if operation=='broken_pool':return [{'code':'600099','trade_date':str(kwargs['day'])}]
        raise Unavailable('mock unsupported')

def test_cross_day_cohorts_and_noon_baseline(tmp_path,config,quote):
    calendar=TradingCalendar(Path(__file__).parents[1]/'config/calendar.json')
    day=quote.timestamp.date();prev=calendar.previous(day);now=datetime(2026,9,4,22,tzinfo=TZ)
    pool=[{'code':'600001','board_count':1,'source':'eastmoney','trade_date':str(prev)}, {'code':'600002','board_count':3,'source':'eastmoney','trade_date':str(prev)}]
    write_json(tmp_path/'data/cache/market_daily'/f'{prev}.json',{'trade_date':str(prev),'as_of_time':str(prev)+'T22:00:00+08:00','limit_pool':pool,'limit_pool_complete':True,'amount':2e8,'quote_coverage':1})
    q2=quote.model_copy(update={'code':'600002','price':9.,'change_pct':-10.,'amount':1e8})
    current=[{**pool[0],'board_count':2,'trade_date':str(day)},{'code':'600003','source':'eastmoney','board_count':1,'trade_date':str(day)}]
    q3=quote.model_copy(update={'code':'600003'})
    context=build_market_context([quote,q2,q3],current,ContextCollector(day),config,tmp_path,calendar,day,now,quality={'coverage':1})
    assert context['break_rate']==pytest.approx(1/3)
    assert context['yesterday_limit_up']['mean_return_pct']==0
    assert context['promotion']['1_to_2']['rate']==1
    assert context['promotion']['2_to_3']['status']=='NO_SAMPLE'
    assert context['promotion']['3_to_4']['rate']==0
    assert context['high_board_loss']['negative_fraction']==1
    # Missing old cohort members cannot disappear from the denominator.
    partial=build_market_context([quote,q3],current,ContextCollector(day),config,tmp_path,calendar,day,now)
    assert partial['yesterday_limit_up']['coverage']==.5
    assert partial['promotion']['3_to_4']['rate'] is None
    assert next(x for x in partial['factor_statuses'] if x['id']=='yesterday_premium')['status']=='PARTIAL'
    # At noon, full-day totals must never be used as an equal-time baseline.
    noon=quote.model_copy(update={'timestamp':datetime(2026,9,4,11,30,tzinfo=TZ)})
    out=build_market_context([noon],[],ContextCollector(day,0),config,tmp_path,calendar,day,datetime(2026,9,4,12,tzinfo=TZ),quality={'coverage':1})
    assert out['market_amount']['ratio_5d'] is None

def test_cache_increment_does_not_bridge_missing_day(tmp_path,config,bars,quote):
    source=FrameSource(config,bars,'fixture',0);store=HistoryStore(tmp_path,Collector([source]),config)
    end=bars.timestamp.iloc[-1].date();now=bars.timestamp.iloc[-1]+timedelta(hours=7)
    store.fetch('600001',end,now)
    q=quote.model_copy(update={'timestamp':now+timedelta(days=3),'previous_close':bars.close.iloc[-1]})
    with pytest.raises(Unavailable):store.fetch('600001',end+timedelta(days=3),now+timedelta(days=3),quote=q,previous_trade_day=end+timedelta(days=2))

def test_market_amount_requires_consecutive_complete_days(tmp_path,config,quote):
    calendar=TradingCalendar(Path(__file__).parents[1]/'config/calendar.json')
    day=quote.timestamp.date();now=datetime(2026,9,4,22,tzinfo=TZ);cursor=day
    for _ in range(20):
        cursor=calendar.previous(cursor)
        write_json(tmp_path/'data/cache/market_daily'/f'{cursor}.json',dict(trade_date=str(cursor),as_of_time=str(cursor)+'T22:00:00+08:00',amount=5e7,quote_coverage=1))
    result=build_market_context([quote],[],ContextCollector(day,0),config,tmp_path,calendar,day,now,quality={'coverage':1})
    assert result['market_amount']['ratio_20d']==2
    partial=build_market_context([quote],[],ContextCollector(day,0),config,tmp_path,calendar,day,now,quality={'coverage':.9})
    assert partial['market_amount']['ratio_5d'] is None
    # An incomplete immediately preceding session invalidates older baselines.
    prior=calendar.previous(day)
    write_json(tmp_path/'data/cache/market_daily'/f'{prior}.json',dict(trade_date=str(prior),as_of_time=str(prior)+'T22:00:00+08:00',amount=5e7,quote_coverage=.8))
    incomplete=build_market_context([quote],[],ContextCollector(day,0),config,tmp_path,calendar,day,now,quality={'coverage':1})
    assert incomplete['market_amount']['history_days']==0
    assert incomplete['market_amount']['ratio_5d'] is None
