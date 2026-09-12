"""Project frozen evidence into the new UI without changing historical signals."""
import argparse
import copy
from datetime import datetime
from pathlib import Path
import pandas as pd
import yaml
from src.models import Quote
from src.utils.calendar import TZ
from src.utils.io import read_json,write_json,clean
from src.stocks.engine import analyze_stocks
from src.research.stocks import select,attach


def project(root, day):
    path=root/'data/history'/day.replace('-','/')/'2200'
    run=read_json(path/'stage_results.json')
    if not run or run['status']!='COMPLETE': raise ValueError('valid close archive required')
    original_id=run['run_id']; config=yaml.safe_load((root/'config/settings.yaml').read_text())
    quotes=[Quote.model_validate(q) for q in clean(pd.read_parquet(path/'daily_quotes.parquet').to_dict('records'))]
    factors={r['stock_code']:{k:v for k,v in r.items() if k!='stock_code'} for r in clean(pd.read_parquet(path/'factor_snapshot.parquet').to_dict('records'))}
    cutoff=datetime.fromisoformat(run['as_of_time'])
    for q in quotes:
        if q.timestamp>cutoff or q.timestamp.astimezone(TZ).date().isoformat()!=day: raise ValueError('quote date mismatch')
        f=factors.get(q.code)
        if not f: continue
        if not f.get('as_of_time') or datetime.fromisoformat(f['as_of_time'])>cutoff: raise ValueError('future factor')
        cache=root/'data/cache/history'/f'history_{q.code}.parquet'
        if cache.exists():
            bars=pd.read_parquet(cache)
            bars=bars[pd.to_datetime(bars.timestamp,utc=True)<=cutoff].sort_values('timestamp')
            if len(bars)>=61 and pd.Timestamp(bars.timestamp.iloc[-1]).astimezone(TZ).date().isoformat()==day and abs(bars.close.iloc[-1]-q.price)<.0051:
                f['bars']=clean(bars.tail(65).to_dict('records'))
    stocks=analyze_stocks(quotes,factors,run['sectors'],run['membership'],run['events'],run['market'],config,run.get('limit_pool',[]))
    selected,changes=select(stocks,'2200',config)
    snapshot=copy.deepcopy(run);snapshot.update(pools=selected,transitions=changes,quotes=[q.model_dump(mode='json') for q in quotes])
    now=datetime.now(TZ).isoformat();attach(snapshot,config,generated_at=now)
    projection={'kind':'POST_HOC_RESEARCH','generated_at':now,'quote_date':day,
        'note':f'基于{day}冻结收盘行情与已存档{len(factors)}只历史因子重做个股研究；这是重构后的补充分析，不改写当时任务，不计入前瞻收益。下次正式晚间任务启用最多250只的独立个股采集通道。'}
    result={'base_run_id':original_id,'quote_date':day,'mode':'live','projection':projection,
            'pools':selected,'stock_research':snapshot['stock_research']}
    write_json(root/'dashboard/data/research_overlay.json',result)
    keep={s['stock_code'] for group in selected.values() for s in group}
    seed={'base_run_id':original_id,'quote_date':day,'generated_at':now,'pools':selected,
          'quotes':[q.model_dump(mode='json') for q in quotes if q.code in keep],
          'factors':{k:v for k,v in factors.items() if k in keep},'stock_research':snapshot['stock_research']}
    write_json(root/'data/latest/stock_research_seed.json',seed)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--date',required=True);parser.add_argument('--root',default='.')
    args=parser.parse_args();r=project(Path(args.root).resolve(),args.date)
    print({k:len(v) for k,v in r['pools'].items()})
