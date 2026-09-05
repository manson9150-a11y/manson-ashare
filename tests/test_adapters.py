from datetime import datetime
import pytest
from src.collectors.base import Collector,Unavailable
from src.collectors.public import TencentAdapter,SinaAdapter,EastmoneyAdapter
from src.utils.calendar import TZ

class Fake:
    reliability_level=.8
    timestamp=None
    def __init__(self,config,name,priority,response=None):self.config=config;self.source_name=name;self.fallback_priority=priority;self.response=response
    def fetch(self,operation,**kwargs):
        if self.response is None:raise Unavailable('failure')
        return self.response

def test_fallback_and_log(quote,config):
    c=Collector([Fake(config,'primary',0),Fake(config,'backup',1,[quote])])
    assert c.fetch('quotes')[0].fallback
    assert c.logs[0]['success'] is False and c.logs[1]['is_fallback'] is True

def test_bad_data_triggers_fallback(quote,config):
    c=Collector([Fake(config,'old',0,[quote.model_copy(update={'source':'stale'})]),Fake(config,'new',1,[quote])])
    def accept(rows):
        if rows[0].source=='stale':raise Unavailable('stale')
        return rows
    assert c.fetch('quotes',accept=accept)[0].source=='fixture'

def test_all_fail_isolated(config):
    c=Collector([Fake(config,'down',0)])
    with pytest.raises(Unavailable):c.fetch('quotes')
    assert len(c.logs)==1 and c.logs[0]['error']=='Unavailable'

def test_tencent_normalization(config):
    fields=['0']*60
    for k,v in {1:'测试',2:'600001',3:'11',4:'10',5:'10',6:'100',30:'20260904150000',32:'10',33:'11',34:'10',37:'11',38:'1',44:'5',47:'11',48:'9',49:'1.2'}.items():fields[k]=v
    q=TencentAdapter(config).normalize('v_sh600001="'+'~'.join(fields)+'";')[0]
    assert q.volume==10000 and q.amount==110000 and q.float_cap==500000000
    assert q.timestamp==datetime(2026,9,4,15,tzinfo=TZ)

def test_missing_timestamp_never_invented(config):
    assert EastmoneyAdapter(config).normalize([{'f12':'600001','f14':'test','f2':10}])==[]
