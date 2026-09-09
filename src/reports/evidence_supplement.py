"""Publish dated source evidence separately from frozen strategy reports."""
from datetime import datetime
from pathlib import Path
import argparse
import math
import pandas as pd
from src.utils.calendar import TZ
from src.utils.io import read_json, write_json


def build(probe, quotes, now=None):
    now=now or datetime.now(TZ)
    pool=probe['limit_pool']
    day=pool['trade_date']
    checked=datetime.fromisoformat(probe['as_of_time'])
    finished=datetime.fromisoformat(probe.get('verified_at',probe.get('event_cutoff_time',probe['as_of_time'])))
    if (pool['status']!='AVAILABLE' or checked.tzinfo is None or finished.tzinfo is None
            or checked>finished or finished>now or checked.astimezone(TZ).date().isoformat()!=day
            or pool['count']!=len(pool['rows'])):
        raise ValueError('invalid probe dates or incomplete pool')
    names={q['code']:q['name'] for q in quotes if str(q['timestamp'])[:10]==day}
    seen=set();rows=[]
    for row in pool['rows']:
        code=row['code'];boards=row.get('board_count')
        if (not isinstance(code,str) or len(code)!=6 or not code.isdigit() or code in seen
                or row.get('trade_date')!=day or type(boards) is not int or boards<1
                or not isinstance(row.get('limit_up_price'),(int,float))
                or not math.isfinite(row['limit_up_price']) or row['limit_up_price']<=0):
            raise ValueError('invalid limit-up row')
        seen.add(code)
        rows.append({**row,'name':names.get(code,''),'identity_basis':'vendor_limit_price'})
    events=[]
    for event in probe.get('events',[]):
        proof=event.get('verification') or {}
        if not proof: continue
        observed=datetime.fromisoformat(proof.get('observed_at',finished.isoformat()))
        if observed.tzinfo is None or observed>finished: raise ValueError('future event evidence')
        events.append(event)
    return {'schema_version':1,'kind':'MARKET_EVIDENCE_SUPPLEMENT','trade_date':day,
            'observed_at':checked.isoformat(),'finished_at':finished.isoformat(),
            'limit_pool':rows,'limit_source':'eastmoney',
            'catalyst_evidence':probe.get('catalyst_evidence',{}),'events':events,
            'note':'盘后补充采集，仅展示市场涨停记录与正文核验；未重算或改写已完成的策略候选池。'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    probe=read_json(args.input);day=probe['limit_pool']['trade_date']
    archive=root/'data/history'/day.replace('-','/')/'1600/daily_quotes.parquet'
    quotes=pd.read_parquet(archive).to_dict('records') if archive.exists() else []
    result=build(probe,quotes)
    write_json(root/'dashboard/data/evidence_supplement.json',result)
    print(f"Published evidence for {day}: {len(result['limit_pool'])} limit-up records; {len(result['events'])} reviewed documents")


if __name__=='__main__':main()
