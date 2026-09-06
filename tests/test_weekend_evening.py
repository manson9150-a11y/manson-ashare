from datetime import date, datetime
from pathlib import Path

from src.pipeline import Pipeline
from src.utils.calendar import TZ
from src.utils.io import read_json, write_json
from src.bootstrap import load_seed

PROJECT=Path(__file__).resolve().parents[1]
DAY=date(2026,9,6)
TARGET=date(2026,9,7)


def prepare(tmp_path,config,monkeypatch):
    seed=read_json(PROJECT/'data/bootstrap/2026-09-07.json')
    write_json(tmp_path/'data/bootstrap/2026-09-07.json',seed)
    p=Pipeline(PROJECT,tmp_path,'live',config)
    monkeypatch.delenv('GOOGLE_DOC_ID',raising=False)
    monkeypatch.setattr(p.announcements,'fetch',lambda *a,**kw: [])
    return p,seed


def codes(run):
    return {s['stock_code'] for g in run['pools'].values() for s in g}


def test_weekend_evening_publishes_current_date_and_seeds_morning(tmp_path,config,monkeypatch):
    p,old=prepare(tmp_path,config,monkeypatch)
    run=p.run(DAY,'2130',datetime(2026,9,6,21,35,tzinfo=TZ))
    assert run['status']=='COMPLETE',run.get('errors')
    assert run['date']=='2026-09-06' and run['quote_date']=='2026-09-04'
    assert run['stage_label']=='周末晚间二筛' and run['weekend_review']['next_trading_date']=='2026-09-07'
    assert codes(run)<=codes(old)
    assert all(s['date']=='2026-09-06' for g in run['pools'].values() for s in g)
    assert (tmp_path/'data/pending/2026-09-06-2130.json').exists()
    assert not (tmp_path/'data/history/2026/09/04/2130/stage_results.json').exists()
    new=load_seed(tmp_path,TARGET,datetime(2026,9,7,7,31,tzinfo=TZ),p.calendar,config)
    assert new['bootstrap_origin']['weekend_evening_run_id']==run['run_id']
    assert codes(new)==codes(run)
    morning=p.run(TARGET,'0730',datetime(2026,9,7,7,31,tzinfo=TZ))
    assert morning['status']=='COMPLETE' and morning['predecessor']['run_id']==run['run_id']
    assert codes(morning)<=codes(run)


def test_weekend_gate_rejects_early_and_other_nontrading_stages(tmp_path,config,monkeypatch):
    p,seed=prepare(tmp_path,config,monkeypatch)
    assert p.run(DAY,'2130',datetime(2026,9,6,20,50,tzinfo=TZ))['status']=='OUTSIDE_STAGE_WINDOW'
    assert p.run(DAY,'1600',datetime(2026,9,6,16,tzinfo=TZ))['status']=='NON_TRADING_DAY'
    assert p.run(date(2026,9,13),'2130',datetime(2026,9,13,21,35,tzinfo=TZ))['status']=='NON_TRADING_DAY'
    assert read_json(tmp_path/'data/bootstrap/2026-09-07.json')['run_id']==seed['run_id']


def test_weekend_repeat_does_not_refresh_or_duplicate_report(tmp_path,config,monkeypatch):
    p,_=prepare(tmp_path,config,monkeypatch)
    first=p.run(DAY,'2130',datetime(2026,9,6,21,35,tzinfo=TZ))
    def must_not_run(*a,**kw):
        raise AssertionError('A completed snapshot must not be recomputed')
    monkeypatch.setattr(p,'compute',must_not_run)
    second=p.run(DAY,'2130',datetime(2026,9,6,22,tzinfo=TZ))
    assert second['run_id']==first['run_id']
    assert len(list((tmp_path/'data/pending').glob('*.json')))==1


def test_empty_evening_pool_still_provides_valid_morning_chain(tmp_path,config,monkeypatch):
    config['candidate_pool']['min_score']=101
    p,_=prepare(tmp_path,config,monkeypatch)
    evening=p.run(DAY,'2130',datetime(2026,9,6,21,35,tzinfo=TZ))
    assert evening['status']=='COMPLETE' and not codes(evening)
    morning=p.run(TARGET,'0730',datetime(2026,9,7,7,31,tzinfo=TZ))
    assert morning['status']=='COMPLETE' and not codes(morning)
