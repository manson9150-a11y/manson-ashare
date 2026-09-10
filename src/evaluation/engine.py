"""Prospective price observations with explicit signal times, never execution returns."""
import statistics
from datetime import date, datetime, timedelta
from src.utils.io import read_json,write_json

OUTCOMES=['next_open_return','next_close_return','next_high_return','next_low_return','next_limit_up','next_3d_return','next_5d_return']

def metrics(records):
    rows=[r for r in records if r.get('next_close_return') is not None]
    returns=[r['next_close_return'] for r in rows]
    limits=[r['next_limit_up'] for r in rows if r.get('next_limit_up') is not None]
    daily={}
    for r in rows:daily.setdefault(r['date'],[]).append(r['next_close_return'])
    equity=peak=1.;drawdown=0.
    for day in sorted(daily):
        equity*=1+statistics.mean(daily[day])/100;peak=max(peak,equity);drawdown=min(drawdown,(equity/peak-1)*100)
    definitions=sorted({r.get('observation_definition','旧口径：报告日期下一交易日收盘相对快照基价；盘前可能跨两交易日') for r in rows})
    return {'sample_size':len(rows),'independent_days':len(daily),'window_start':min(daily) if daily else None,'window_end':max(daily) if daily else None,
        'metric_version':2 if records and all(r.get('metric_version')==2 for r in records) else 1,
        'win_rate':statistics.mean(x>0 for x in returns) if returns else None,'average_return':statistics.mean(returns) if returns else None,
        'median_return':statistics.median(returns) if returns else None,'max_drawdown':drawdown if returns else None,
        'next_day_limit_up_rate':statistics.mean(limits) if limits else None,
        'top3_hit_rate':statistics.mean(r['next_close_return']>0 for r in rows if r['rank']<=3) if any(r['rank']<=3 for r in rows) else None,
        'top5_hit_rate':statistics.mean(r['next_close_return']>0 for r in rows if r['rank']<=5) if any(r['rank']<=5 for r in rows) else None,
        'definition':'；'.join(definitions or ['等待前瞻观察'])+'。同阶段价格观察，不含费用、滑点、停牌及涨停成交约束；不是策略净收益。'}

def first_close_date(run,calendar):
    signal=datetime.fromisoformat(run['as_of_time'])
    day=date.fromisoformat(run['date'])
    if signal.hour<15 and calendar.is_trading_day(day): return day
    cursor=day+timedelta(days=1)
    while not calendar.is_trading_day(cursor): cursor+=timedelta(days=1)
    return cursor

def update_outcomes(root,run,calendar,config):
    path=root/'data/history/outcomes.json'
    records=read_json(path,[])
    lookup={(r['date'],r['stage'],r['stock_code'],r['pool']):r for r in records}
    first=first_close_date(run,calendar)
    stage=run['stage']
    definition=('前交易日收盘至信号当日收盘' if stage in ('0800','0730','0830') else
                '信号当日上午收盘至当日收盘' if stage in ('1200','1135') else '信号当日收盘至下一交易日收盘')
    for pool,group in run.get('pools',{}).items():
        for s in group:
            key=(run['date'],stage,s['stock_code'],pool)
            lookup.setdefault(key,{'date':run['date'],'stage':stage,'stock_code':s['stock_code'],'pool':pool,'rank':s['rank'],
                'position_type':s['position_type'],'base_price':s['price'],'base_quote_date':s['timestamp'][:10],
                'signal_time':run['as_of_time'],'first_observation_date':str(first),'observation_definition':definition,'metric_version':2,
                'sector_score':s['sector_score'],'distance_ma20':s.get('distance_ma20'),'atr':s.get('atr'),**{k:None for k in OUTCOMES}})
    if stage in ('1600','2200') and run['data_quality']['status']!='RED':
        quotes={q['code']:q for q in run.get('quotes',[])}
        today=date.fromisoformat(run['date'])
        for r in lookup.values():
            # Legacy observations stay frozen and separated, never silently relabel past results.
            if r.get('metric_version')!=2: continue
            start=date.fromisoformat(r['first_observation_date'])
            if start>today or (today-start).days>config['storage']['evaluation_window_days']:continue
            n=len(calendar.sessions(start,today));q=quotes.get(r['stock_code'])
            if not q or q['timestamp'][:10]!=str(today) or r['base_price']<=0:continue
            if n==1:
                r['next_close_return']=(q['price']/r['base_price']-1)*100
                # A full-day high/low or opening price precedes a noon signal; don't use it.
                intraday_signal=r['stage'] in ('1200','1135') and r['date']==str(today)
                if not intraday_signal:
                    for field,name in [('open','open'),('high','high'),('low','low')]:r[f'next_{name}_return']=(q[field]/r['base_price']-1)*100
                r['next_limit_up']=abs(q['price']-q['limit_up_price'])<.0051 if q.get('limit_up_price') else None
                r['observed_close_date']=str(today)
            if n in (3,5):r[f'next_{n}d_return']=(q['price']/r['base_price']-1)*100
    records=list(lookup.values());write_json(path,records)
    groups={}
    for r in records:
        key=r['stage']+'/'+r['pool']+('/旧口径' if r.get('metric_version')!=2 else '')
        groups.setdefault(key,[]).append(r)
    result={k:metrics(v) for k,v in groups.items()}
    write_json(root/'data/latest/evaluation.json',result)
    return result
