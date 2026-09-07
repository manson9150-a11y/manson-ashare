"""Read-only live probe; optional current-time dashboard supplement, no historical rewrite."""
import argparse
from datetime import datetime
from pathlib import Path
import yaml
from src.collectors.wudao import WudaoResearch
from src.utils.calendar import TradingCalendar, TZ
from src.utils.io import write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--publish-supplement',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    config=yaml.safe_load((root/'config/settings.yaml').read_text())
    now=datetime.now(TZ)
    cal=TradingCalendar(root/'config/calendar.json')
    day=now.date() if cal.is_trading_day(now.date()) and now.hour>=15 else cal.previous(now.date())
    client=WudaoResearch(config)
    result=client.collect(day,now,'probe')
    result['supplement']=True
    result['source_logs']=client.logs
    write_json(root/'artifacts/wudao-probe.json',result)
    print('WUDAO',result['status'],'date',result['trade_date'],'member_themes',len(result['membership']),'errors',result['errors'])
    for key in ['featured','industry']:
        panel=result.get(key)
        if panel: print(key,'snapshot',panel['snapshot_time'],'first',panel['rows'][0]['themeName'])
    if not result['featured'] or not result['industry'] or not result['membership']: raise SystemExit(1)
    if args.publish_supplement:
        write_json(root/'dashboard/data/wudao.json',result)

if __name__=='__main__': main()
