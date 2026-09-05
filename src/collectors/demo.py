"""Deterministic simulated data, never used as a live-source fallback."""
from datetime import datetime,timedelta
import numpy as np
import pandas as pd
from src.models import Quote,Event
from src.utils.calendar import TZ

class DemoData:
    def __init__(self,calendar,as_of,stage):
        self.calendar,self.as_of,self.stage=calendar,as_of,stage
        day=as_of.date() if stage in ('1600','2130','1135') else calendar.previous(as_of.date())
        self.day=day
        self.universe=[{'code':f'{600001+i:06}','name':f'模拟企业{i+1:02}','industry':['算力基础设施','半导体','机器人','新能源','有色金属'][i%5]} for i in range(80)]
        self.membership=[{'id':f'DEMO{k}','name':name,'kind':'industry' if k<3 else 'concept','source':'SIMULATED','codes':[u['code'] for i,u in enumerate(self.universe) if i%5==k]} for k,name in enumerate(['算力基础设施','半导体','机器人','新能源','有色金属'])]
        self.frames={};self.quotes=[]
        dates=calendar.sessions(day-timedelta(days=150),day)[-85:]
        for i,u in enumerate(self.universe):
            rng=np.random.default_rng(400+i)
            close=(12+i/3)*np.cumprod(1+rng.normal(.002 if i%5<4 else -.002,.007,len(dates)))
            close[-1]=close[-2]*(1.1 if i%13==0 else 1.025 if i%5<3 else .992)
            volume=rng.integers(2000000,6000000,len(dates)).astype(float);volume[-1]*=1.6
            opening=close*np.where(np.arange(len(close))==len(close)-1,.98,.997)
            frame=pd.DataFrame({'timestamp':[datetime.combine(d,datetime.min.time()).replace(hour=15,tzinfo=TZ) for d in dates],'open':opening,'high':close*(1.025 if i%13==0 else 1.012),'low':np.minimum(opening,close)*(.975 if i%13==0 else .988),'close':close,'volume':volume,'amount':volume*close,'source':'SIMULATED'})
            if stage=='1135': frame.loc[len(frame)-1,'timestamp']=datetime.combine(day,datetime.min.time()).replace(hour=11,minute=30,tzinfo=TZ)
            self.frames[u['code']]=frame
            row=frame.iloc[-1]
            self.quotes.append(Quote(code=u['code'],name=u['name'],price=row.close,previous_close=close[-2],open=row.open,high=row.high,low=row.low,volume=row.volume,amount=row.amount,change_pct=(close[-1]/close[-2]-1)*100,industry=u['industry'],timestamp=row.timestamp.to_pydatetime(),fetched_at=as_of,source='SIMULATED',limit_up_price=close[-2]*1.1,limit_down_price=close[-2]*.9))
    def events(self):
        t=self.as_of-timedelta(hours=1)
        return [Event(event_id='demo-contract',canonical_id='demo-contract',stock_code='600017',event_type='重大合同',title='[模拟] 已核验重大合同，仅用于功能验收',event_time=t,publish_time=t,source='SIMULATED',url='https://example.com/demo',reliability=1,directness=1,impact_score=85,verified=True)]
