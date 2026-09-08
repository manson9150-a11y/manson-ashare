"""Read-only current-time smoke check; never writes a formal stage or Google Doc."""
from pathlib import Path
from datetime import datetime
import json
import yaml
from src.collectors.public import EastmoneyAdapter
from src.catalysts.evidence import CatalystEvidence
from src.utils.calendar import TZ
from src.utils.io import write_json


def main():
    project=Path(__file__).resolve().parents[2]
    config=yaml.safe_load((project/'config/settings.yaml').read_text())
    output=project/'artifacts/candidate-evidence-verification'
    as_of=datetime.now(TZ)
    result={'mode':'READ_ONLY_SOURCE_PROBE','as_of_time':as_of.isoformat()}
    try:
        pool=EastmoneyAdapter(config).fetch('limit_pool',day=as_of.date())
        result['limit_pool']={'status':'AVAILABLE','count':len(pool),'trade_date':str(as_of.date()),'rows':pool}
    except Exception as exc:
        result['limit_pool']={'status':'UNAVAILABLE','error':type(exc).__name__}
    service=CatalystEvidence(config,output)
    events=service.verify(service.discover(as_of),as_of)
    result['catalyst_evidence']=service.status
    result['events']=[e.model_dump(mode='json') for e in events]
    write_json(output/'result.json',result)
    print(json.dumps({'limit_pool':{k:v for k,v in result['limit_pool'].items() if k!='rows'},'catalyst_evidence':service.status},ensure_ascii=False))


if __name__=='__main__': main()
