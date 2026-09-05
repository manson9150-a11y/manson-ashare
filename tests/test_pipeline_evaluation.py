from datetime import date,datetime
from pathlib import Path
import json
import pytest
from src.pipeline import Pipeline
from src.utils.calendar import TZ
from src.utils.io import read_json
from src.evaluation.engine import metrics
PROJECT=Path(__file__).parents[1]

def codes(run):return {s['stock_code'] for g in run['pools'].values() for s in g}

def test_complete_overnight_cycle(tmp_path,config):
    p=Pipeline(PROJECT,tmp_path,'demo',config)
    results={}
    for day,stage in [(date(2026,9,3),'1600'),(date(2026,9,3),'2130')]+[(date(2026,9,4),s) for s in ['0730','0830','1135','1600','2130']]:
        r=p.run(day,stage);results[(str(day),stage)]=r
        assert r['status']=='COMPLETE',r.get('errors')
        assert r['errors']==[]
        assert all(s.get('subjective_probability') is None for g in r['pools'].values() for s in g)
    assert all(results[('2026-09-04','1600')]['pools'].values())
    evening=results[('2026-09-03','2130')];overnight=results[('2026-09-04','0730')];pre=results[('2026-09-04','0830')];midday=results[('2026-09-04','1135')]
    assert codes(overnight)<=codes(evening) and len(codes(overnight))<=12
    assert codes(pre)<=codes(overnight) and len(codes(pre))<=10
    assert codes(midday)<=codes(pre) and len(codes(midday))<=5
    assert {s['stock_code'] for s in midday['validations']}==codes(pre)
    assert overnight['quote_date']=='2026-09-03'
    assert len(list(tmp_path.glob('data/history/*/*/*/*/factor_snapshot.parquet')))==7
    assert (tmp_path/'reports/2026-09-04.md').exists()
    assert not list((tmp_path/'data/pending').glob('*.json'))
    frozen=p.run(date(2026,9,4),'0830')
    assert frozen['run_id']==pre['run_id']

def test_missing_predecessor_no_reselection(tmp_path,config):
    p=Pipeline(PROJECT,tmp_path,'demo',config)
    r=p.run(date(2026,9,4),'0730')
    assert r['status']=='MISSING_PREDECESSOR' and not codes(r)

def test_nontrading_no_fake_report(tmp_path,config):
    p=Pipeline(PROJECT,tmp_path,'live',config)
    r=p.run(date(2026,9,5),'1600')
    assert r['status']=='NON_TRADING_DAY'
    assert not (tmp_path/'data/latest/latest.json').exists()
    assert not (tmp_path/'reports/2026-09-05.md').exists()

def test_late_run_refuses_future_data(tmp_path,config):
    p=Pipeline(PROJECT,tmp_path,'live',config)
    r=p.run(date(2026,9,4),'0830',datetime(2026,9,4,15,tzinfo=TZ))
    assert r['status']=='OUTSIDE_STAGE_WINDOW'

def test_total_provider_outage_still_reports(tmp_path,config,monkeypatch):
    p=Pipeline(PROJECT,tmp_path,'live',config)
    def fail(*args,**kwargs):raise ConnectionError('offline')
    monkeypatch.setattr(p.collector,'fetch',fail)
    monkeypatch.delenv('GOOGLE_DOC_ID',raising=False)
    r=p.run(date(2026,9,4),'1600',datetime(2026,9,4,16,1,tzinfo=TZ))
    assert r['status']=='DEGRADED' and r['data_quality']['status']=='RED' and not codes(r)
    assert (tmp_path/'reports/2026-09-04.md').exists()
    assert r['google_docs']['current_report']=='DEGRADED_LOCAL_ONLY'

def test_empty_evaluation_does_not_invent_winrate():
    result=metrics([])
    assert result['sample_size']==0 and result['win_rate'] is None and result['max_drawdown'] is None

def test_evaluation_known_cohort():
    records=[{'date':'2026-09-01','rank':1,'next_close_return':10,'next_limit_up':True},{'date':'2026-09-02','rank':2,'next_close_return':-10,'next_limit_up':False}]
    r=metrics(records)
    assert r['win_rate']==.5 and r['average_return']==0 and r['median_return']==0
    assert r['max_drawdown']==pytest.approx(-10)

def test_workflow_schedule_matches_stage():
    import yaml
    from src.cli import SCHEDULE
    workflow=yaml.load((PROJECT/'.github/workflows/research.yml').read_text(),Loader=yaml.BaseLoader)
    assert {v['cron'] for v in workflow['on']['schedule']}==set(SCHEDULE)
    assert workflow['concurrency']['cancel-in-progress']=='false'

def test_empty_valid_pool_preserves_chain(tmp_path,config):
    # A strict strategy can yield no names without turning valid market data into an outage.
    config['candidate_pool']['min_score']=101
    p=Pipeline(PROJECT,tmp_path,'demo',config)
    for day,stage in [(date(2026,9,3),'1600'),(date(2026,9,3),'2130'),(date(2026,9,4),'0730'),(date(2026,9,4),'0830'),(date(2026,9,4),'1135')]:
        r=p.run(day,stage)
        assert r['status']=='COMPLETE',r.get('errors')
        assert not codes(r)
