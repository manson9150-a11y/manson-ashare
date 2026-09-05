"""Public, unauthenticated endpoints. No anti-bot bypass; no implicit cached live data."""
from datetime import datetime
import json
import re
import pandas as pd
from src.models import Quote
from src.utils.calendar import TZ
from .base import Adapter, Unavailable

def symbol(code):
    return ('sh' if code.startswith('6') else 'bj' if code.startswith(('4', '8', '92')) else 'sz') + code

def number(value):
    try:
        return float(value) if value not in ('-', '', None) else None
    except (ValueError, TypeError):
        return None

def bar_frame(rows, source):
    data = []
    for r in rows:
        data.append({'timestamp': datetime.fromisoformat(r[0] + 'T15:00:00').replace(tzinfo=TZ), 'open': float(r[1]), 'close': float(r[2]), 'high': float(r[3]), 'low': float(r[4]), 'volume': float(r[5]) * 100, 'amount': number(r[6]) if len(r) > 6 else None, 'source': source})
    return pd.DataFrame(data)

class EastmoneyAdapter(Adapter):
    source_name = 'eastmoney'
    fallback_priority = 0
    def listing(self, fs, fields):
        rows = []
        page = 1
        while True:
            payload = self.get('https://push2.eastmoney.com/api/qt/clist/get', params={'pn': page, 'pz': 100, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2, 'fid': 'f3', 'fs': fs, 'fields': fields}).json().get('data')
            if not payload or not payload.get('diff'):
                break
            batch = payload['diff']
            batch = list(batch.values()) if isinstance(batch, dict) else batch
            rows.extend(batch)
            if len(rows) >= payload['total']:
                break
            page += 1
            if page > 100:
                raise Unavailable('pagination overflow')
        return rows
    def fetch(self, operation, **kwargs):
        if operation in ('universe', 'quotes'):
            rows = self.listing('m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81', 'f2,f3,f5,f6,f8,f10,f12,f14,f15,f16,f17,f18,f21,f100,f124')
            if operation == 'universe':
                return [{'code': r['f12'], 'name': r['f14'], 'industry': r.get('f100')} for r in rows]
            if kwargs.get('codes'):
                wanted = set(kwargs['codes'])
                rows = [r for r in rows if r['f12'] in wanted]
            return self.normalize(rows)
        if operation == 'history':
            code = kwargs['code']
            payload = self.get('https://push2his.eastmoney.com/api/qt/stock/kline/get', params={'secid': ('1' if code.startswith('6') else '0') + '.' + code, 'klt': 101, 'fqt': 0, 'beg': '0', 'end': kwargs['end'].strftime('%Y%m%d'), 'lmt': self.config['sources']['history_bars'], 'fields1': 'f1,f2,f3,f4,f5,f6', 'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'}).json().get('data')
            if not payload:
                raise Unavailable('no history')
            return bar_frame([line.split(',')[:7] for line in payload['klines'][-self.config['sources']['history_bars']:]], self.source_name)
        if operation == 'sectors':
            result = []
            for kind, fs in [('industry', 'm:90+t:2'), ('concept', 'm:90+t:3')]:
                for r in self.listing(fs, 'f2,f3,f6,f12,f14,f104,f105,f124'):
                    result.append({'id': r['f12'], 'name': r['f14'], 'kind': kind, 'change_pct': number(r['f3']), 'timestamp': datetime.fromtimestamp(r['f124'], TZ).isoformat() if number(r.get('f124')) else None, 'source': self.source_name})
            return result
        if operation == 'members':
            return [r['f12'] for r in self.listing('b:' + kwargs['sector_id'], 'f12')]
        if operation == 'limit_pool':
            data = self.get('https://push2ex.eastmoney.com/getTopicZTPool', params={'ut': '7eea3edcaed734bea9cbfc24409ed9894', 'dpt': 'wz.ztzt', 'Pageindex': 0, 'pagesize': 1000, 'sort': 'fbt:asc', 'date': kwargs['day'].strftime('%Y%m%d'), '_': int(datetime.now(TZ).timestamp() * 1000)}).json().get('data')
            if not data:
                return []
            return [{'code': r['c'], 'board_count': r.get('lbc'), 'first_seal': r.get('fbt'), 'last_seal': r.get('lbt'), 'break_count': r.get('zbc'), 'seal_amount': r.get('fund'), 'source': self.source_name, 'trade_date': str(kwargs['day'])} for r in data.get('pool', [])]
        raise Unavailable('unsupported')
    def normalize(self, payload, **kwargs):
        rows = []
        for r in payload:
            try:
                if not number(r.get('f124')):
                    continue
                rows.append(Quote(code=r['f12'], name=r['f14'], price=r['f2'], previous_close=r['f18'], open=r['f17'], high=r['f15'], low=r['f16'], volume=float(r['f5']) * 100, amount=r['f6'], change_pct=r['f3'], turnover=number(r.get('f8')), volume_ratio=number(r.get('f10')), float_cap=number(r.get('f21')), industry=r.get('f100') if r.get('f100') != '-' else None, timestamp=datetime.fromtimestamp(r['f124'], TZ), fetched_at=datetime.now(TZ), source=self.source_name))
            except (ValueError, TypeError, KeyError):
                continue
        return rows

class TencentAdapter(Adapter):
    source_name = 'tencent'
    fallback_priority = 1
    def fetch(self, operation, **kwargs):
        if operation == 'universe':
            rows=[]
            offset=0
            while True:
                data=self.get('https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList',params={'_appver':'11.17.0','board_code':'aStock','sort_type':'price','direct':'down','offset':offset,'count':200}).json()['data']
                batch=data['rank_list']
                rows.extend({'code':r['code'][2:],'name':r['name'],'industry':None} for r in batch)
                offset+=len(batch)
                if offset>=int(data['total']) or not batch:break
                if offset>10000:raise Unavailable('pagination overflow')
            return list({r['code']:r for r in rows}.values())
        if operation == 'quotes':
            codes = kwargs.get('codes', [])
            rows = []
            for i in range(0, len(codes), 60):
                response = self.get('https://qt.gtimg.cn/q=' + ','.join(symbol(c) for c in codes[i:i+60]))
                rows.extend(self.normalize(response.content.decode('gb18030', errors='replace')))
            return rows
        if operation == 'history':
            code = symbol(kwargs['code'])
            data = self.get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get', params={'param': f'{code},day,,{kwargs["end"]:%Y-%m-%d},{self.config["sources"]["history_bars"]},'}).json()
            rows = data.get('data', {}).get(code, {}).get('day', [])
            # Tencent raw daily series is deliberately unadjusted. Missing turnover amount remains null.
            return bar_frame([r[:6] for r in rows], self.source_name)
        raise Unavailable('unsupported')
    def normalize(self, payload, **kwargs):
        result = []
        for match in re.finditer(r'v_\w+="([^"]*)"', payload):
            r = match.group(1).split('~')
            try:
                if len(r) < 49:
                    continue
                q = Quote(code=r[2], name=r[1], price=r[3], previous_close=r[4], open=r[5], high=r[33], low=r[34], volume=float(r[6]) * 100, amount=float(r[37]) * 10000, change_pct=r[32], turnover=number(r[38]), volume_ratio=number(r[49]) if len(r)>49 else None, float_cap=float(r[44]) * 100000000 if number(r[44]) else None, timestamp=datetime.strptime(r[30], '%Y%m%d%H%M%S').replace(tzinfo=TZ), fetched_at=datetime.now(TZ), source=self.source_name, limit_up_price=number(r[47]), limit_down_price=number(r[48]))
                result.append(q)
            except (ValueError, TypeError, IndexError):
                continue
        return result

class SinaAdapter(Adapter):
    source_name = 'sina'
    fallback_priority = 2
    def fetch(self, operation, **kwargs):
        if operation == 'universe':
            rows = []
            for page in range(1, 100):
                batch = self.get('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData', params={'page': page, 'num': 100, 'sort': 'symbol', 'asc': 1, 'node': 'hs_a', 'symbol': '', '_s_r_a': 'page'}).json()
                if not batch:
                    break
                rows.extend({'code': r['code'], 'name': r['name'], 'industry': None} for r in batch)
                if len(batch) < 100:
                    break
            return rows
        if operation == 'quotes':
            result = []
            codes = kwargs.get('codes', [])
            for i in range(0, len(codes), 60):
                r = self.get('https://hq.sinajs.cn/list=' + ','.join(symbol(c) for c in codes[i:i+60]))
                result.extend(self.normalize(r.content.decode('gb18030', errors='replace')))
            return result
        raise Unavailable('unsupported')
    def normalize(self, payload, **kwargs):
        result = []
        for match in re.finditer(r'hq_str_\w{2}(\d{6})="([^"]*)"', payload):
            r = match.group(2).split(',')
            try:
                result.append(Quote(code=match.group(1), name=r[0], open=r[1], previous_close=r[2], price=r[3], high=r[4], low=r[5], volume=r[8], amount=r[9], change_pct=(float(r[3])/float(r[2])-1)*100, timestamp=datetime.fromisoformat(r[30]+'T'+r[31]).replace(tzinfo=TZ), fetched_at=datetime.now(TZ), source=self.source_name))
            except (ValueError, TypeError, IndexError, ZeroDivisionError):
                continue
        return result

class QuickTinyAdapter(Adapter):
    source_name = 'quicktiny'
    fallback_priority = 99
    reliability_level = 0.5
    def fetch(self, operation, **kwargs):
        raise Unavailable('disabled pending public access and terms verification')
    def normalize(self, payload, **kwargs):
        return []
