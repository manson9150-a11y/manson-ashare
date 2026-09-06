import hashlib
from datetime import datetime, timedelta
from pathlib import Path
import html
import re
from urllib.parse import urlencode
from src.models import Event
from src.utils.calendar import TZ
from .base import Adapter, Unavailable
from src.utils.io import read_json, write_json


def event_kind(title, config):
    kind = '其他公告'
    for word, value in {**config['catalyst']['positive_keywords'], **config['catalyst']['risk_keywords']}.items():
        if word in title:
            kind = value
    return kind


class CninfoAnnouncementAdapter(Adapter):
    """Public disclosure search; complete bounded queries or explicit failure."""
    source_name = 'cninfo_announcements'
    reliability_level = 0.95
    fallback_priority = 0

    def __init__(self, config, cache_path=None):
        super().__init__(config)
        self.client.headers['Referer'] = 'https://www.cninfo.com.cn/'
        self.cache_path = Path(cache_path) if cache_path else None
        self.first_seen = read_json(self.cache_path, {}) if self.cache_path else {}

    def fetch(self, operation, **kwargs):
        if operation != 'events':
            raise Unavailable('unsupported')
        codes = list(dict.fromkeys(kwargs.get('codes', [])))
        if not codes:
            return []
        now = datetime.now(TZ)
        settings = self.config.get('announcements', {})
        start = now.date() - timedelta(days=settings.get('lookback_days', 7))
        directory = self.get('https://www.cninfo.com.cn/new/data/szse_stock.json').json()
        organizations = {r['code']: r['orgId'] for r in directory.get('stockList', [])}
        if any(code not in organizations for code in codes):
            raise Unavailable('requested security missing from CNINFO directory')
        result = []
        for code in codes:
            received = 0
            for page in range(1, settings.get('max_pages_per_stock', 3) + 1):
                payload = {'pageNum': str(page), 'pageSize': '30', 'column': 'szse',
                           'tabName': 'fulltext', 'plate': '', 'stock': f'{code},{organizations[code]}',
                           'searchkey': '', 'secid': '', 'category': '', 'trade': '',
                           'seDate': f'{start}~{now.date()}', 'sortName': '', 'sortType': '', 'isHLtitle': 'false'}
                data = self.post('https://www.cninfo.com.cn/new/hisAnnouncement/query', data=payload).json()
                if not isinstance(data, dict) or 'totalAnnouncement' not in data or 'announcements' not in data:
                    raise Unavailable('unexpected announcement response')
                total = int(data['totalAnnouncement'])
                rows = data['announcements']
                if rows is None and total == 0:
                    rows = []
                if not isinstance(rows, list) or any(row.get('secCode') != code for row in rows):
                    raise Unavailable('announcement security mismatch')
                normalized = self.normalize(rows)
                if len(normalized) != len(rows):
                    raise Unavailable('incomplete announcement normalization')
                result.extend(normalized)
                received += len(rows)
                if not data.get('hasMore') and received >= total:
                    break
                if not rows:
                    raise Unavailable('announcement pagination incomplete')
            else:
                raise Unavailable('announcement pagination budget exceeded')
        if self.cache_path:
            self.first_seen = {k: v for k, v in self.first_seen.items() if v[:10] >= str(start)}
            write_json(self.cache_path, self.first_seen)
        return result

    def normalize(self, payload, **kwargs):
        result = []
        for row in payload:
            try:
                code, aid = row['secCode'], str(row['announcementId'])
                if not re.fullmatch(r'\d{6}', code) or not aid.isdigit():
                    continue
                title = html.unescape(re.sub(r'<[^>]+>', '', row['announcementTitle'])).strip()
                if not title or not row.get('announcementTime'):
                    continue
                published = datetime.fromtimestamp(float(row['announcementTime']) / 1000, TZ)
                precision = 'date' if not (published.hour or published.minute or published.second or published.microsecond) else 'second'
                key = f'cninfo:{aid}:{code}'
                observed = self.first_seen.setdefault(key, datetime.now(TZ).isoformat())
                url = 'https://www.cninfo.com.cn/new/disclosure/detail?' + urlencode({
                    'stockCode': code, 'announcementId': aid, 'orgId': row['orgId'],
                    'announcementTime': str(published.date())})
                result.append(Event(event_id=hashlib.sha256(key.encode()).hexdigest()[:20],
                                    canonical_id=key, stock_code=code, title=title,
                                    event_type=event_kind(title, self.config), event_time=published,
                                    publish_time=published, publish_time_precision=precision,
                                    first_seen_at=datetime.fromisoformat(observed), source=self.source_name,
                                    url=url, reliability=self.reliability_level, directness=1,
                                    verified=False, impact_score=None))
            except (ValueError, KeyError, TypeError, OverflowError, OSError):
                continue
        return result

class AnnouncementAdapter(Adapter):
    source_name = 'eastmoney_announcements'
    reliability_level = 0.85
    fallback_priority = 1
    def fetch(self, operation, **kwargs):
        if operation != 'events':
            raise Unavailable('unsupported')
        events=[]
        # Bounded candidate requests; no all-market news flood.
        codes=kwargs.get('codes',[])
        for i in range(0,len(codes),10):
            data=self.get('https://np-anotice-stock.eastmoney.com/api/security/ann',params={'sr':-1,'page_size':50,'page_index':1,'ann_type':'A','client_source':'web','stock_list':','.join(codes[i:i+10])}).json()
            content=data.get('data')
            if not isinstance(content,dict) or not isinstance(content.get('list'),list):
                raise Unavailable('unexpected Eastmoney announcement response')
            rows=content['list']
            if int(content.get('total_hits',len(rows)))>len(rows):
                raise Unavailable('Eastmoney announcement result truncated')
            normalized=self.normalize(rows)
            if rows and not normalized:
                raise Unavailable('Eastmoney announcement timestamps unavailable')
            events.extend(e for e in normalized if e.stock_code in codes[i:i+10])
        return events
    def normalize(self,payload,**kwargs):
        result=[]
        c=self.config['catalyst']
        for row in payload:
            # display_time is publication time; notice_date alone is not an intraday timestamp.
            raw=row.get('display_time') or row.get('eiTime')
            if not raw or len(raw)<19:
                continue
            try:
                published=datetime.fromisoformat(raw[:19]).replace(tzinfo=TZ)
                title=row['title']
                kind='其他公告'
                for word,value in c['positive_keywords'].items():
                    if word in title: kind=value
                for word,value in c['risk_keywords'].items():
                    if word in title: kind=value
                aid=row['art_code']
                for stock in row.get('codes',[]):
                    code=stock.get('stock_code','')
                    if len(code)!=6: continue
                    result.append(Event(event_id=hashlib.sha256((aid+code).encode()).hexdigest()[:20],canonical_id=aid+':'+code,stock_code=code,event_type=kind,title=title,event_time=published,publish_time=published,source=self.source_name,url=f'https://data.eastmoney.com/notices/detail/{code}/{aid}.html',reliability=self.reliability_level,directness=1,verified=False,impact_score=None))
            except (ValueError,KeyError,TypeError):
                continue
        return result
