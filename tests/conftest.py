from datetime import datetime
from pathlib import Path
import pytest,yaml
import numpy as np
import pandas as pd
from src.models import Quote,Event
from src.utils.calendar import TZ
@pytest.fixture
def config():
    result=yaml.safe_load((Path(__file__).parents[1]/'config/settings.yaml').read_text())
    result['catalyst_evidence']['enabled']=False  # Offline tests opt in with mocked transports.
    return result
@pytest.fixture
def bars():
    c=np.arange(1,81,dtype=float)+100
    return pd.DataFrame({'timestamp':pd.date_range('2026-05-01 15:00',periods=80,tz=TZ),'open':c-.5,'high':c+1,'low':c-1,'close':c,'volume':1000000.,'amount':100000000.,'source':'fixture'})
@pytest.fixture
def quote():
    return Quote(code='600001',name='测试企业',price=11,previous_close=10,open=10.1,high=11,low=10,volume=1000000,amount=100000000,change_pct=10,timestamp=datetime(2026,9,4,15,tzinfo=TZ),fetched_at=datetime(2026,9,4,16,tzinfo=TZ),source='fixture',limit_up_price=11,limit_down_price=9)
@pytest.fixture
def event():
    return Event(event_id='1',stock_code='600001',event_type='重大合同',title='公司重大合同公告',event_time=datetime(2026,9,4,7,tzinfo=TZ),publish_time=datetime(2026,9,4,7,tzinfo=TZ),source='official',url='https://example.com/1',reliability=1,directness=1,impact_score=80,verified=True)
