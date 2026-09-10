from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from .io import read_json
TZ = ZoneInfo('Asia/Shanghai')

class CalendarUnknown(ValueError):
    pass

class TradingCalendar:
    def __init__(self, path):
        self.config = read_json(path)
    def is_trading_day(self, day: date):
        if day.year not in self.config['verified_years']:
            raise CalendarUnknown(f'{day.year} 交易日历未核验，禁止按工作日猜测')
        s = day.isoformat()
        if s in self.config['extra_closed']:
            return False
        if s in self.config['extra_open']:
            return True
        return day.weekday() < 5 and not any(a <= s <= b for a, b in self.config['closed_ranges'])
    def previous(self, day):
        for i in range(1, 32):
            d = day - timedelta(days=i)
            if self.is_trading_day(d):
                return d
        raise CalendarUnknown('无法确定前一交易日')
    def sessions(self, start, end):
        result = []
        while start <= end:
            if self.is_trading_day(start):
                result.append(start)
            start += timedelta(days=1)
        return result

def stage_time(day, stage, config):
    return datetime.fromisoformat(f"{day}T{config['stages'][stage]['time']}:00").replace(tzinfo=TZ)

def next_scheduled_time(now, calendar, config):
    """Use the verified exchange calendar, including weekends and holidays."""
    for offset in range(32):
        day=now.astimezone(TZ).date()+timedelta(days=offset)
        try:
            if not calendar.is_trading_day(day): continue
        except CalendarUnknown:
            return None
        for stage in config.get('active_stages',['0800','1200','2200']):
            planned=stage_time(day,stage,config)
            if planned>now: return planned.isoformat()
    return None
