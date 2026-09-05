"""Prospective cohorts only. Missing sessions stay null; no fabricated backtest."""
import statistics
from datetime import date,timedelta
from src.utils.io import read_json,write_json

OUTCOMES=['next_open_return','next_close_return','next_high_return','next_low_return','next_limit_up','next_3d_return','next_5d_return']

def metrics(records):
    rows=[r for r in records if r.get('next_close_return') is not None]
    returns=[r['next_close_return'] for r in rows]
    limits=[r['next_limit_up'] for r in rows if r.get('next_limit_up') is not None]
    # Equal-weight daily cohort curve, not a sequence of overlapping individual trades.
    daily={}
    for r in rows:daily.setdefault(r['date'],[]).append(r['next_close_return'])
    equity=peak=1.;drawdown=0.
    for day in sorted(daily):
        equity*=1+statistics.mean(daily[day])/100;peak=max(peak,equity);drawdown=min(drawdown,(equity/peak-1)*100)
    return {'sample_size':len(rows),'win_rate':statistics.mean(x>0 for x in returns) if returns else None,'average_return':statistics.mean(returns) if returns else None,'median_return':statistics.median(returns) if returns else None,'max_drawdown':drawdown if returns else None,'next_day_limit_up_rate':statistics.mean(limits) if limits else None,'top3_hit_rate':statistics.mean(r['next_close_return']>0 for r in rows if r['rank']<=3) if any(r['rank']<=3 for r in rows) else None,'top5_hit_rate':statistics.mean(r['next_close_return']>0 for r in rows if r['rank']<=5) if any(r['rank']<=5 for r in rows) else None,'definition':'同阶段/同池日等权观察组合；命中=次日收盘上涨；不含费用、滑点、停牌与涨停无法成交约束'}

def update_outcomes(root,run,calendar,config):
    path=root/'data/history/outcomes.json'
    records=read_json(path,[])
    lookup={(r['date'],r['stage'],r['stock_code'],r['pool']):r for r in records}
    for pool,group in run.get('pools',{}).items():
        for s in group:
            key=(run['date'],run['stage'],s['stock_code'],pool)
            lookup.setdefault(key,{'date':run['date'],'stage':run['stage'],'stock_code':s['stock_code'],'pool':pool,'rank':s['rank'],'position_type':s['position_type'],'base_price':s['price'],'base_quote_date':s['timestamp'][:10],'sector_score':s['sector_score'],'distance_ma20':s.get('distance_ma20'),'atr':s.get('atr'),**{k:None for k in OUTCOMES}})
    if run['stage']=='1600' and run['data_quality']['status']!='RED':
        quotes={q['code']:q for q in run.get('quotes',[])}
        today=date.fromisoformat(run['date'])
        for r in lookup.values():
            if r['date']>=run['date']:continue
            start=date.fromisoformat(r['date'])
            if (today-start).days>config['storage']['evaluation_window_days']:continue
            sessions=calendar.sessions(start+timedelta(days=1),today)
            n=len(sessions);q=quotes.get(r['stock_code'])
            if not q or r['base_price']<=0:continue
            if n==1:
                for field,name in [('open','open'),('price','close'),('high','high'),('low','low')]:r[f'next_{name}_return']=(q[field]/r['base_price']-1)*100
                r['next_limit_up']=abs(q['price']-q['limit_up_price'])<.0051 if q.get('limit_up_price') else None
            if n in (3,5):r[f'next_{n}d_return']=(q['price']/r['base_price']-1)*100
    records=list(lookup.values());write_json(path,records)
    groups={}
    for r in records:groups.setdefault(r['stage']+'/'+r['pool'],[]).append(r)
    result={k:metrics(v) for k,v in groups.items()}
    write_json(root/'data/latest/evaluation.json',result)
    return result
