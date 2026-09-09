from datetime import datetime
from copy import deepcopy
import pytest
from src.reports.evidence_supplement import build
from src.utils.calendar import TZ

def probe():
    return {'as_of_time':'2026-09-08T23:16:00+08:00','verified_at':'2026-09-08T23:18:00+08:00',
            'limit_pool':{'status':'AVAILABLE','trade_date':'2026-09-08','count':1,
                          'rows':[{'code':'002403','board_count':4,'trade_date':'2026-09-08','limit_up_price':13.65}]}}

def test_supplement_retains_real_timestamps_and_uses_only_same_day_names():
    p=probe();before=deepcopy(p)
    r=build(p,[{'code':'002403','name':'旧名','timestamp':'2026-09-07T15:00:00+08:00'}],datetime(2026,9,8,23,30,tzinfo=TZ))
    assert r['limit_pool'][0]['name']=='' and r['observed_at']==p['as_of_time']
    assert r['kind']=='MARKET_EVIDENCE_SUPPLEMENT' and 'pools' not in r and p==before

@pytest.mark.parametrize('fault',['date','count','duplicate','boards','price','future'])
def test_invalid_source_evidence_is_not_published(fault):
    p=probe();row=p['limit_pool']['rows'][0]
    if fault=='date':row['trade_date']='2026-09-07'
    if fault=='count':p['limit_pool']['count']=2
    if fault=='duplicate':p['limit_pool']['rows'].append(dict(row));p['limit_pool']['count']=2
    if fault=='boards':row['board_count']=True
    if fault=='price':row['limit_up_price']=float('nan')
    if fault=='future':p['verified_at']='2026-09-09T23:18:00+08:00'
    with pytest.raises(ValueError):build(p,[],datetime(2026,9,8,23,30,tzinfo=TZ))
