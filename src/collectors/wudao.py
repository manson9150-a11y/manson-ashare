"""Bounded read-only, stateless MCP client. Never invoke user watchlists."""
from datetime import datetime
import json
import math
import os
import re
import httpx
from src.utils.calendar import TZ

URL = 'https://stock.quicktiny.cn/api/mcp'
ALLOWED = {'theme_intraday_capital', 'theme_stocks'}
STOP_CODES = {'DAILY_LIMIT_EXCEEDED', 'FREE_TIER_MARKET_OPEN_RESTRICTED', 'RATE_LIMIT_EXCEEDED'}

class WudaoError(RuntimeError):
    pass

class WudaoResearch:
    def __init__(self, config, key=None, client=None):
        self.config = config.get('wudao', {})
        self.key = key if key is not None else os.environ.get('WUDAO_API_KEY', '')
        self.client = client or httpx.Client(timeout=25, follow_redirects=False)
        self.logs = []
        self.sequence = 0
        self.ready = False
        self.stopped = False

    def rpc(self, method, params=None, notification=False):
        if not self.key: raise WudaoError('NOT_CONFIGURED')
        if self.stopped: raise WudaoError('CIRCUIT_OPEN')
        self.sequence += 1
        body = {'jsonrpc':'2.0', 'method':method, 'params':params or {}}
        if not notification: body['id'] = self.sequence
        r = self.client.post(URL, headers={'Authorization':'Bearer '+self.key,
            'Accept':'application/json, text/event-stream', 'MCP-Protocol-Version':'2025-03-26'}, json=body)
        if r.status_code in (401,403,429):
            self.stopped = True
            raise WudaoError('HTTP_'+str(r.status_code))
        r.raise_for_status()
        if notification: return {}
        if 'application/json' not in r.headers.get('content-type',''): raise WudaoError('NON_JSON_RESPONSE')
        payload = r.json()
        # Provider error messages are never logged verbatim (they can echo headers).
        candidate = payload.get('result',{})
        structured = candidate.get('structuredContent',{}) if isinstance(candidate,dict) else {}
        actual_error = payload.get('error') or (candidate if candidate.get('isError') or structured.get('success') is False else None)
        # initialize.instructions describe possible error codes; they are not errors.
        for code in STOP_CODES:
            if actual_error and code in json.dumps(actual_error):
                self.stopped = True
                raise WudaoError(code)
        if payload.get('error'): raise WudaoError('RPC_ERROR')
        result = payload.get('result')
        if not isinstance(result,dict): raise WudaoError('INVALID_RESULT')
        return result

    def call(self, name, arguments):
        if name not in ALLOWED: raise WudaoError('TOOL_NOT_ALLOWED')
        if not self.ready:
            self.rpc('initialize', {'protocolVersion':'2025-03-26','capabilities':{},
                'clientInfo':{'name':'manson-ashare','version':'1.0'}})
            self.rpc('notifications/initialized', notification=True)
            self.ready = True
        result = self.rpc('tools/call', {'name':name,'arguments':arguments})
        if result.get('isError'): raise WudaoError('TOOL_ERROR')
        payload = result.get('structuredContent')
        if payload is None:
            texts = [c['text'] for c in result.get('content',[]) if c.get('type')=='text']
            try: payload = json.loads(texts[0])
            except (ValueError,IndexError): raise WudaoError('INVALID_PAYLOAD')
        if not isinstance(payload,dict) or payload.get('success') is not True: raise WudaoError('DATA_ERROR')
        data = payload.get('data')
        if not isinstance(data,dict): raise WudaoError('INVALID_DATA')
        # Reject partial upstream results and explicit date mismatches.
        if payload.get('partialErrors') or data.get('partialErrors'): raise WudaoError('PARTIAL_DATA')
        if 'mismatch' in str(payload.get('dateStatus',''))+str(data.get('dateStatus',''))+str(payload.get('qualityWarnings',''))+str(data.get('qualityWarnings','')):
            raise WudaoError('DATE_MISMATCH')
        return data

    def record(self, operation, fn):
        log = dict(source_name='wudao_mcp', operation=operation, fetched_at=datetime.now(TZ).isoformat(),
                   timestamp=None, reliability_level=0.85, fallback_priority=0, is_fallback=False, count=0)
        try:
            data = fn()
            log.update(success=True, count=len(data.get('rows',data.get('codes',[]))), timestamp=data.get('snapshot_time'))
            return data
        except Exception as exc:
            error = str(exc) if isinstance(exc,WudaoError) else type(exc).__name__
            log.update(success=False,error=error)
            raise
        finally: self.logs.append(log)

    @staticmethod
    def number(value):
        if value is None: return None
        value = float(value)
        if not math.isfinite(value): raise WudaoError('NON_FINITE')
        return value

    def ranking(self, day, as_of, universe, stage):
        data = self.call('theme_intraday_capital', {'tradeDate':str(day),'universe':universe,
            'sortBy':'strength' if universe=='featured' else 'pctChg','limit':10,'format':'json'})
        expected = str(day).replace('-','')
        if any(str(data.get(k,'')).replace('-','')!=expected for k in ['tradeDate','actualTradeDate']):
            raise WudaoError('DATE_MISMATCH')
        stamp = datetime.fromisoformat(data.get('snapshotTime','').replace('Z','+00:00'))
        if stamp.tzinfo is None or stamp>as_of or stamp.astimezone(TZ).date()!=day: raise WudaoError('INVALID_SNAPSHOT_TIME')
        if stage=='1135' and (as_of-stamp).total_seconds()>self.config.get('intraday_max_age_minutes',20)*60:
            raise WudaoError('STALE_INTRADAY')
        rows = data.get('rows')
        if not isinstance(rows,list) or not rows: raise WudaoError('EMPTY_RANKING')
        normalized=[]
        for row in rows:
            if not row.get('themeCode') or not row.get('themeName'): raise WudaoError('INVALID_THEME')
            item={k:row[k] for k in ['themeCode','themeName']}
            for field in ['strength','pctChg','amount','mainNetAmount']:
                item[field]=self.number(row.get(field))
            if item['pctChg'] is None or (universe=='featured' and item['strength'] is None): raise WudaoError('MISSING_RANK_METRIC')
            normalized.append(item)
        return {'rows':normalized,'snapshot_time':stamp.isoformat(),'trade_date':str(day),'total':data.get('total')}

    def members(self, row, day, as_of):
        data = self.call('theme_stocks',{'themeCode':row['themeCode'],'tradeDate':str(day).replace('-',''),
            'limit':300,'format':'json'})
        theme=data.get('theme',{}); resolution=data.get('resolution',{})
        rows=data.get('rows',[])
        if not rows: raise WudaoError('EMPTY_MEMBERS')
        if data.get('total',len(rows))>len(rows): raise WudaoError('TRUNCATED_MEMBERS')
        if resolution.get('tradeDate') and str(resolution['tradeDate']).replace('-','')!=str(day).replace('-',''):
            raise WudaoError('DATE_MISMATCH')
        stamp=theme.get('updatedAt') or theme.get('lastFetchedAt')
        if not stamp: raise WudaoError('MEMBERS_TIME_UNKNOWN')
        observed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if observed.tzinfo is None or observed>as_of or (as_of-observed).total_seconds()>7*86400:
            raise WudaoError('MEMBERS_TIME_INVALID')
        codes=sorted({str(r.get('code','')) for r in rows})
        if not all(re.fullmatch(r'\d{6}',c) for c in codes): raise WudaoError('INVALID_STOCK_CODE')
        name=theme.get('name') or resolution.get('resolvedName')
        if not name: raise WudaoError('MEMBERS_NAME_UNKNOWN')
        return {'id':'wudao:'+str(theme.get('kplId') or name),'name':name,'kind':'concept','codes':codes,
            'source':'wudao_mcp','observed_at':datetime.now(TZ).isoformat(),'metadata_updated_at':observed.isoformat(),
            'requested_name':row['themeName'],'match_type':resolution.get('matchType','unknown')}

    def collect(self, day, as_of, stage):
        result={'status':'UNAVAILABLE','trade_date':str(day),'requested_at':as_of.isoformat(),
                'featured':None,'industry':None,'membership':[],'errors':[]}
        for universe in ['featured','industry']:
            try: result[universe]=self.record('ranking_'+universe,lambda u=universe:self.ranking(day,as_of,u,stage))
            except Exception: result['errors'].append(self.logs[-1]['error'])
            if self.stopped: break
        rows=(result.get('featured') or {}).get('rows',[])
        for row in rows[:self.config.get('member_theme_limit',10)]:
            if self.stopped: break
            try:
                member=self.record('members',lambda r=row:self.members(r,day,as_of))
                if member['id'] not in {s['id'] for s in result['membership']}: result['membership'].append(member)
            except Exception: result['errors'].append(self.logs[-1]['error'])
        result['status']='OK' if result['featured'] and result['industry'] and not result['errors'] else 'PARTIAL' if result['featured'] or result['industry'] else 'UNAVAILABLE'
        result['errors']=sorted(set(result['errors']))
        result['finished_at']=datetime.now(TZ).isoformat()
        return result
