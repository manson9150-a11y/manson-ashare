import hashlib
from datetime import datetime
from src.models import Event
from src.utils.calendar import TZ
from .base import Adapter, Unavailable

class AnnouncementAdapter(Adapter):
    source_name = 'eastmoney_announcements'
    reliability_level = 0.85
    fallback_priority = 0
    def fetch(self, operation, **kwargs):
        if operation != 'events':
            raise Unavailable('unsupported')
        events=[]
        # Bounded candidate requests; no all-market news flood.
        codes=kwargs.get('codes',[])
        for i in range(0,len(codes),10):
            data=self.get('https://np-anotice-stock.eastmoney.com/api/security/ann',params={'sr':-1,'page_size':50,'page_index':1,'ann_type':'A','client_source':'web','stock_list':','.join(codes[i:i+10])}).json()
            events.extend(self.normalize(data.get('data',{}).get('list',[])))
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
