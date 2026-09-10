from pathlib import Path
import pytest
from src.evaluation.engine import update_outcomes, metrics
from src.utils.calendar import TradingCalendar
from src.utils.io import read_json

def signal(stage,price,day='2026-09-04'):
    timestamp=day+'T'+({'0800':'08:00','1200':'12:00','2200':'22:00'}[stage])+':00+08:00'
    stock={'stock_code':'600001','rank':1,'position_type':'趋势观察','price':price,'timestamp':timestamp,'sector_score':75}
    return {'date':day,'stage':stage,'as_of_time':timestamp,'pools':{'POOL_B':[stock]},'data_quality':{'status':'GREEN'}}

def test_morning_and_noon_observe_same_day_close(tmp_path,config):
    calendar=TradingCalendar(Path(__file__).parents[1]/'config/calendar.json')
    for stage,price in [('0800',10),('1200',11)]:update_outcomes(tmp_path,signal(stage,price),calendar,config)
    close=signal('2200',12)
    close['quotes']=[dict(code='600001',timestamp='2026-09-04T15:00:00+08:00',price=12,open=10,high=13,low=9)]
    result=update_outcomes(tmp_path,close,calendar,config)
    records={r['stage']:r for r in read_json(tmp_path/'data/history/outcomes.json')}
    assert records['0800']['next_close_return']==pytest.approx(20)
    assert records['1200']['next_close_return']==pytest.approx(100/11)
    assert records['1200']['next_open_return'] is None
    assert records['1200']['next_high_return'] is None
    assert records['2200']['first_observation_date']=='2026-09-07'
    assert records['2200']['next_close_return'] is None
    assert result['1200/POOL_B']['independent_days']==1

def test_observation_rows_are_not_independent_days():
    rows=[dict(date='2026-09-04',rank=i+1,next_close_return=2,next_limit_up=None,metric_version=2) for i in range(30)]
    assert metrics(rows)['sample_size']==30
    assert metrics(rows)['independent_days']==1
