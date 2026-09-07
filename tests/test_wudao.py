import json
from datetime import date, datetime
import httpx
import pytest
from src.collectors.wudao import WudaoResearch, WudaoError
from src.utils.calendar import TZ

NOW=datetime(2026,9,7,17,tzinfo=TZ)
DAY=date(2026,9,7)


def ranking():
    return {'tradeDate':'20260907','actualTradeDate':'20260907','snapshotTime':'2026-09-07T07:05:00Z',
            'rows':[{'themeCode':'801660k','themeName':'通信','strength':21593,'pctChg':2.94}]}


def member():
    return {'theme':{'kplId':'65','name':'光通信设备','updatedAt':'2026-09-06T13:00:00Z'},
            'resolution':{'matchType':'fuzzy','tradeDate':'20260907'},'total':2,
            'rows':[{'code':'300502'},{'code':'300308'}]}


def client(config,handler):
    return WudaoResearch(config,key='test-secret',client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_stateless_post_only_and_actual_resolved_name(config):
    seen=[]
    def handle(req):
        assert req.method=='POST' and str(req.url)=='https://stock.quicktiny.cn/api/mcp'
        assert req.headers['authorization']=='Bearer test-secret'
        body=json.loads(req.content);seen.append(body)
        if body['method']=='initialize':return httpx.Response(200,json={'result':{'protocolVersion':'2025-03-26','instructions':'RATE_LIMIT_EXCEEDED and DAILY_LIMIT_EXCEEDED are possible errors'}})
        if body['method']=='notifications/initialized':return httpx.Response(202)
        name=body['params']['name'];assert name in {'theme_intraday_capital','theme_stocks'}
        data=member() if name=='theme_stocks' else ranking()
        return httpx.Response(200,json={'result':{'structuredContent':{'success':True,'data':data}}})
    c=client(config,handle);r=c.collect(DAY,NOW,'1600')
    assert r['status']=='OK'
    assert r['membership'][0]['name']=='光通信设备'
    assert r['membership'][0]['requested_name']=='通信'
    assert '300502' in r['membership'][0]['codes']
    assert len(seen)==5
    assert 'test-secret' not in json.dumps(c.logs)


@pytest.mark.parametrize('fault',['wrong_date','future','naive','stale','partial','empty','nan'])
def test_bad_snapshots_rejected(config,monkeypatch,fault):
    c=client(config,lambda r:None);data=ranking();as_of=NOW;stage='1600'
    if fault=='wrong_date':data['actualTradeDate']='20260904'
    if fault=='future':data['snapshotTime']='2026-09-07T10:00:00Z'
    if fault=='naive':data['snapshotTime']='2026-09-07T15:00:00'
    if fault=='stale':data['snapshotTime']='2026-09-07T01:31:00Z';as_of=datetime(2026,9,7,11,36,tzinfo=TZ);stage='1135'
    if fault=='empty':data['rows']=[]
    if fault=='nan':data['rows'][0]['pctChg']=float('nan')
    if fault=='partial':
        # Test real response envelope rejection, not a mocked validation.
        c.ready=True
        c.client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'result':{'structuredContent':{'success':True,'data':{**data,'partialErrors':['upstream']}}}})))
    else:monkeypatch.setattr(c,'call',lambda *a:data)
    with pytest.raises((WudaoError,ValueError)):c.ranking(DAY,as_of,'featured',stage)


@pytest.mark.parametrize('status',[401,403,429])
def test_auth_quota_circuit_no_retry(config,status):
    calls=[]
    def handle(req):calls.append(req);return httpx.Response(status,json={'secret':'must never leak'})
    c=client(config,handle);r=c.collect(DAY,NOW,'2130')
    assert r['status']=='UNAVAILABLE' and len(calls)==1
    assert r['errors']==['HTTP_'+str(status)]
    assert 'must never leak' not in json.dumps(c.logs)


def test_no_watchlist_calls_and_no_key(config):
    c=WudaoResearch(config,key='')
    with pytest.raises(WudaoError,match='TOOL_NOT_ALLOWED'):c.call('watchlist_add',{})
    assert c.collect(DAY,NOW,'0730')['status']=='UNAVAILABLE'


@pytest.mark.parametrize('fault',['truncated','future','bad_code','missing_time'])
def test_membership_quality(config,monkeypatch,fault):
    c=WudaoResearch(config,key='x');data=member()
    if fault=='truncated':data['total']=301
    if fault=='future':data['theme']['updatedAt']='2026-09-08T00:00:00Z'
    if fault=='bad_code':data['rows'][0]['code']='bad'
    if fault=='missing_time':data['theme'].pop('updatedAt')
    monkeypatch.setattr(c,'call',lambda *a:data)
    with pytest.raises(WudaoError):c.members(ranking()['rows'][0],DAY,NOW)


def test_explicit_quota_error_stops_remaining_calls(config):
    calls=[]
    def handle(req):
        calls.append(req)
        return httpx.Response(200,json={'error':{'code':-32000,'message':'DAILY_LIMIT_EXCEEDED'}})
    c=client(config,handle);r=c.collect(DAY,NOW,'2130')
    assert r['errors']==['DAILY_LIMIT_EXCEEDED'] and len(calls)==1


@pytest.mark.parametrize('stage',['0730','0830','1135','1600','2130'])
def test_each_formal_stage_requests_wudao_before_analysis(tmp_path,config,monkeypatch,stage):
    from pathlib import Path
    import shutil
    from src.pipeline import Pipeline
    from src.screening.pools import predecessor
    from src.utils.io import read_json
    root=Path(__file__).resolve().parents[1]
    p=Pipeline(root,tmp_path,'live',config)
    key=predecessor(DAY,stage,p.calendar)
    if stage=='0730':
        (tmp_path/'data/bootstrap').mkdir(parents=True)
        shutil.copyfile(root/'data/bootstrap/2026-09-07.json',tmp_path/'data/bootstrap/2026-09-07.json')
    elif key:
        target=p.stage_path(*key);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/target.relative_to(tmp_path),target)
    calls=[]
    def collect(day,as_of,st):
        calls.append((day,st))
        return {'status':'UNAVAILABLE','trade_date':str(day),'requested_at':as_of.isoformat(),'featured':None,'industry':None,'membership':[],'errors':['HTTP_429']}
    monkeypatch.setattr(p.wudao,'collect',collect)
    monkeypatch.setattr(p.announcements,'fetch',lambda *a,**kw:[])
    def offline(*a,**kw):raise ConnectionError('no network in regression')
    monkeypatch.setattr(p.collector,'fetch',offline)
    monkeypatch.delenv('GOOGLE_DOC_ID',raising=False)
    hour,minute=map(int,config['stages'][stage]['time'].split(':'))
    r=p.run(DAY,stage,datetime(2026,9,7,hour,minute,tzinfo=TZ))
    assert calls==[(date(2026,9,4) if stage in ('0730','0830') else DAY,stage)]
    assert r['wudao']['status']=='UNAVAILABLE'
    assert any('HTTP_429' in w for w in r['warnings'])
    assert read_json(p.stage_path(DAY,stage))['wudao']['status']=='UNAVAILABLE'
