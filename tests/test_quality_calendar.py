from datetime import date,datetime,timedelta
from pathlib import Path
import pytest
from pydantic import ValidationError
from src.utils.calendar import TradingCalendar,CalendarUnknown,TZ
from src.normalizers.quality import validate_quotes,validate_bars
from src.screening.pools import predecessor

@pytest.fixture
def calendar():return TradingCalendar(Path(__file__).parents[1]/'config/calendar.json')
@pytest.mark.parametrize('day,expected',[('2026-09-04',True),('2026-09-05',False),('2026-10-01',False),('2026-10-08',True),('2026-02-23',False),('2026-02-24',True),('2026-10-10',False),('2026-05-05',False),('2026-01-02',False)])
def test_calendar(calendar,day,expected):assert calendar.is_trading_day(date.fromisoformat(day)) is expected

def test_calendar_unknown(calendar):
    with pytest.raises(CalendarUnknown):calendar.is_trading_day(date(2027,1,5))

def test_friday_is_monday_predecessor(calendar):
    assert predecessor(date(2026,9,7),'0730',calendar)==(date(2026,9,4),'2130')

def test_timestamp_required(quote):
    from src.models import Quote
    data=quote.model_dump();data['timestamp']=datetime(2026,9,4)
    with pytest.raises(ValidationError):Quote.model_validate(data)

@pytest.mark.parametrize('kind,reason',[('future','FUTURE_QUOTE'),('old','STALE_TRADING_DATE'),('cache','HISTORICAL_CACHE'),('suspended','SUSPENDED_OR_NO_TRADE'),('invalid','INVALID_OHLC')])
def test_rejection(quote,config,kind,reason):
    if kind=='future':quote.timestamp=datetime(2026,9,4,16,1,tzinfo=TZ)
    if kind=='old':quote.timestamp-=timedelta(days=1)
    if kind=='cache':quote.cached=True
    if kind=='suspended':quote.suspended=True
    if kind=='invalid':quote.high=10.5
    rows,q=validate_quotes([quote],datetime(2026,9,4,16,tzinfo=TZ),date(2026,9,4),config,'1600')
    assert not rows and q['status']=='RED' and q['rejected'][0]['reason']==reason

def test_morning_rejects_afternoon_and_1129(quote,config):
    for hour,minute in [(15,0),(11,29)]:
        quote.timestamp=datetime(2026,9,4,hour,minute,tzinfo=TZ)
        rows,q=validate_quotes([quote],datetime(2026,9,4,11,35,tzinfo=TZ),date(2026,9,4),config,'1135')
        assert not rows
    quote.timestamp=datetime(2026,9,4,11,30,tzinfo=TZ)
    assert validate_quotes([quote],datetime(2026,9,4,11,35,tzinfo=TZ),date(2026,9,4),config,'1135')[0]

def test_conflict_and_dedup(quote,config):
    other=quote.model_copy(update={'price':10.9,'change_pct':9.,'reliability':1.0,'source':'official'})
    rows,q=validate_quotes([quote,other],datetime(2026,9,4,16,tzinfo=TZ),date(2026,9,4),config,'1600',1)
    assert len(rows)==1 and rows[0].source=='official' and q['conflicts']==['600001']

def test_history_cutoff(bars,config):
    cutoff=bars.timestamp.iloc[30]
    result=validate_bars(bars,cutoff,config)
    assert len(result)==31 and result.timestamp.max()<=cutoff

def test_data_coverage(quote,config):
    _,quality=validate_quotes([quote],datetime(2026,9,4,16,tzinfo=TZ),date(2026,9,4),config,'1600',5000)
    assert quality['status']=='RED'
