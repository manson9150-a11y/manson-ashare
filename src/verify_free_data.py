"""Read-only source probe. Does not publish reports or rebuild earlier stages."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import argparse
import json
import yaml
from src.collectors.public import EastmoneyAdapter, TencentAdapter, SinaAdapter
from src.collectors.baostock import BaoStockAdapter
from src.normalizers.quality import validate_bars
from src.utils.calendar import TZ, TradingCalendar
from src.utils.io import write_json


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('artifacts/free_sources.json'));args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]
    config=yaml.safe_load((project/'config/settings.yaml').read_text())
    config['sources'].update(attempts=1,timeout_seconds=10)
    now=datetime.now(TZ);calendar=TradingCalendar(project/'config/calendar.json')
    day=now.date() if now.hour>=16 and calendar.is_trading_day(now.date()) else calendar.previous(now.date())
    def probe(cls):
        adapter=cls(config)
        try:
            frame=validate_bars(adapter.fetch('history',code='600000',end=day),now,config)
            fresh=len(frame)>=61 and frame.timestamp.iloc[-1].astimezone(TZ).date()==day
            complete=fresh and 'amount' in frame and bool((frame.amount.tail(21).notna() & (frame.amount.tail(21)>0)).all())
            return {'source':adapter.source_name,'fresh':bool(fresh),'amount_complete':bool(complete),'rows':len(frame),
                    'close':float(frame.close.iloc[-1]) if len(frame) else None,
                    'amount':float(frame.amount.iloc[-1]) if complete else None}
        except Exception as e:
            return {'source':adapter.source_name,'fresh':False,'amount_complete':False,'error':type(e).__name__}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(probe,[EastmoneyAdapter,TencentAdapter,SinaAdapter,BaoStockAdapter]))
    complete=[r for r in results if r['amount_complete']]
    agrees=len(complete)>=2 and max(r['close'] for r in complete)/min(r['close'] for r in complete)<1.005 and max(r['amount'] for r in complete)/min(r['amount'] for r in complete)<1.001
    result={'observed_at':now.isoformat(),'quote_date':str(day),'sample_code':'600000','sources':results,
            'cross_check_passed':agrees,'scope':'单标的只读连通性检查，不代表全市场覆盖；不生成历史阶段或候选'}
    write_json(args.output,result);print(json.dumps(result,ensure_ascii=False))
    if not agrees:raise SystemExit(1)

if __name__=='__main__':main()
