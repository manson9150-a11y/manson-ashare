from datetime import date,datetime
from pathlib import Path
import pytest
from src.pipeline import Pipeline
from src.utils.calendar import TZ,next_scheduled_time
from src.utils.io import read_json,write_json
from src.collectors.wudao import WudaoResearch,WudaoError
from src.google_docs.writer import DocsOutbox,ACTIVE_STAGES,marker
from tests.test_reports_docs import FakeDocs

PROJECT=Path(__file__).parents[1]

def test_three_stage_cycle_and_independent_evening(tmp_path,config):
    p=Pipeline(PROJECT,tmp_path,'demo',config)
    results=[]
    for day,stage in [(date(2026,9,3),'2200'),(date(2026,9,4),'0800'),(date(2026,9,4),'1200'),(date(2026,9,4),'2200')]:
        result=p.run(day,stage)
        assert result['status']=='COMPLETE',result.get('errors')
        assert result['errors']==[]
        results.append(result)
    assert results[0].get('predecessor') is None
    assert results[1]['predecessor']['stage']=='2200'
    assert results[2]['predecessor']['stage']=='0800'
    assert results[3].get('predecessor') is None
    assert (p.stage_path(date(2026,9,4),'2200').parent/'daily_quotes.parquet').exists()
    assert results[1]['quote_date']=='2026-09-03'
    assert results[2]['quote_date']=='2026-09-04'
    assert [x['stage'] for x in results[-1]['active_schedule']]==['0800','1200','2200']
    assert '08:00' in (tmp_path/'reports/2026-09-04.md').read_text()
    assert p.run(date(2026,9,4),'0800')['run_id']==results[1]['run_id']

def test_monday_reads_friday_and_legacy_migration(tmp_path,config):
    p=Pipeline(PROJECT,tmp_path,'demo',config)
    old=p.run(date(2026,9,4),'1600')
    result=p.run(date(2026,9,7),'0800')
    assert result['status']=='COMPLETE'
    assert result['predecessor']['stage']=='1600'
    assert result['quote_date']=='2026-09-04'
    assert read_json(p.stage_path(date(2026,9,4),'1600'))['run_id']==old['run_id']
    assert next_scheduled_time(datetime(2026,9,4,23,tzinfo=TZ),p.calendar,config)=='2026-09-07T08:00:00+08:00'

def test_new_stage_refuses_missing_or_outside_window(tmp_path,config):
    p=Pipeline(PROJECT,tmp_path,'demo',config)
    assert p.run(date(2026,9,4),'0800')['status']=='MISSING_PREDECESSOR'
    live=Pipeline(PROJECT,tmp_path,'live',config)
    assert live.run(date(2026,9,4),'2200',datetime(2026,9,4,16,tzinfo=TZ))['status']=='OUTSIDE_STAGE_WINDOW'

def test_noon_wudao_accepts_morning_close_only(config,monkeypatch):
    c=WudaoResearch(config,key='test')
    payload={'tradeDate':'20260904','actualTradeDate':'20260904','snapshotTime':'2026-09-04T11:30:00+08:00',
             'rows':[{'themeCode':'a','themeName':'测试','strength':20,'pctChg':1}]}
    monkeypatch.setattr(c,'call',lambda *a:payload)
    now=datetime(2026,9,4,12,0,tzinfo=TZ)
    assert c.ranking(now.date(),now,'featured','1200')['rows']
    payload['snapshotTime']='2026-09-04T11:20:00+08:00'
    with pytest.raises(WudaoError):c.ranking(now.date(),now,'featured','1200')
    payload['snapshotTime']='2026-09-04T13:00:00+08:00'
    with pytest.raises(WudaoError):c.ranking(now.date(),now,'featured','1200')

def test_new_docs_schedule_and_same_day_transition(tmp_path):
    session=FakeDocs();out=DocsOutbox(tmp_path,session,'id')
    out.enqueue('2026-09-09','1600','历史收盘')
    assert out.flush()['status']=='SYNCED'
    for st,_ in ACTIVE_STAGES:
        out.enqueue('2026-09-09',st,'新阶段'+st)
        assert out.flush()['status']=='SYNCED'
    assert session.text.count('[MANSON:2026-09-09:SCHEDULE_V2]')==1
    assert '历史收盘' in session.text
    assert all('新阶段'+st in session.text for st,_ in ACTIVE_STAGES)
    new=FakeDocs();out=DocsOutbox(tmp_path/'next',new,'id')
    out.enqueue('2026-09-10','0800','新早报');out.flush()
    assert marker('2026-09-10','1200') in new.text
    assert marker('2026-09-10','0730') not in new.text
