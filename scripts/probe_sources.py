"""Read-only live smoke check; never publishes investment candidates or changes state."""
from datetime import datetime
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import yaml
from src.collectors.public import TencentAdapter,EastmoneyAdapter,SinaAdapter
from src.utils.calendar import TZ,TradingCalendar
from src.normalizers.quality import validate_bars
from src.factors.technical import technical
from src.utils.io import write_json
root=Path(__file__).resolve().parents[1]
config=yaml.safe_load((root/'config/settings.yaml').read_text())
config['sources']['timeout_seconds']=8
now=datetime.now(TZ);calendar=TradingCalendar(root/'config/calendar.json');day=calendar.previous(now.date())
result={'checked_at':now.isoformat(),'purpose':'LIVE_ADAPTER_SMOKE_ONLY','checks':[]}
for adapter in [TencentAdapter(config),EastmoneyAdapter(config),SinaAdapter(config)]:
 for operation in ['quotes','history']:
  try:
   rows=adapter.fetch(operation,codes=['600519','000001'],code='600519',end=day)
   if len(rows)==0:raise ValueError('empty')
   row={'source':adapter.source_name,'operation':operation,'success':True,'count':len(rows)}
   if operation=='quotes':row['quotes']=[q.model_dump(mode='json') for q in rows]
   else:row['factors']=technical(validate_bars(rows,now,config));row['last_date']=str(rows.timestamp.iloc[-1])
   result['checks'].append(row)
   print(adapter.source_name,operation,'OK',len(rows),flush=True)
  except Exception as exc:
   result['checks'].append({'source':adapter.source_name,'operation':operation,'success':False,'error':type(exc).__name__})
   print(adapter.source_name,operation,type(exc).__name__,flush=True)
write_json(root/'artifacts/live-source-check.json',result)
