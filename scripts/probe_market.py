"""A weekend read-only coverage diagnostic. Never a formal trading-stage report."""
from pathlib import Path
from datetime import datetime
import sys,json,yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.collectors.public import EastmoneyAdapter,TencentAdapter,SinaAdapter
from src.collectors.base import Collector,Unavailable
from src.utils.calendar import TZ,TradingCalendar
from src.normalizers.quality import validate_quotes
from src.utils.io import write_json,read_json
from src.market.engine import market_score
from src.sectors.engine import sector_scores
root=Path(__file__).resolve().parents[1];config=yaml.safe_load((root/'config/settings.yaml').read_text());config['sources']['timeout_seconds']=8
now=datetime.now(TZ);cal=TradingCalendar(root/'config/calendar.json');day=cal.previous(now.date())
collector=Collector([EastmoneyAdapter(config),TencentAdapter(config),SinaAdapter(config)])
universe=collector.fetch('universe');print('Universe:',len(universe),flush=True)
quotes=collector.fetch('quotes',codes=[s['code'] for s in universe]);print('Quotes:',len(quotes),flush=True)
valid,quality=validate_quotes(quotes,now,day,config,'2130',max(config['sources']['expected_universe_min'],len(universe)))
meta=read_json(root/'artifacts/live-metadata/data/latest/membership.json',{})
sectors=sector_scores(valid,meta.get('sectors',[]),{},config)
result={'mode':'READ_ONLY_DIAGNOSTIC','not_a_trading_report':True,'checked_at':now.isoformat(),'quote_date':str(day),'universe':len(universe),'quotes':len(quotes),'quality':quality,'sector_count':len(sectors),'mapped_codes':len({c for s in meta.get('sectors',[]) for c in s['codes']}),'market':market_score(valid,config,quality),'sources':collector.logs}
write_json(root/'artifacts/live-market-check.json',result)
print(json.dumps({k:result[k] for k in ['mode','quote_date','universe','quotes','sector_count','quality']},ensure_ascii=False),flush=True)
