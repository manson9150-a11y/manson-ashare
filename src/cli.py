import argparse, json, shutil
from pathlib import Path
from datetime import date, datetime
from src.pipeline import Pipeline
from src.utils.calendar import TZ
from src.utils.io import read_json
STAGES=['0730','0830','1135','1600','2130']
SCHEDULE={'30 23 * * 0-4':'0730','30 0 * * 1-5':'0830','35 3 * * 1-5':'1135','0 8 * * 1-5':'1600','30 13 * * 1-5':'2130'}
def main():
    parser=argparse.ArgumentParser(description='MANSON A-share batch research')
    parser.add_argument('--stage',choices=STAGES+['full_pipeline'],default='1600'); parser.add_argument('--schedule',default='')
    parser.add_argument('--date',type=date.fromisoformat); parser.add_argument('--demo',action='store_true'); parser.add_argument('--output',type=Path)
    parser.add_argument('--replay',action='store_true',help='Read stored result without current network data')
    args=parser.parse_args(); project=Path(__file__).resolve().parents[1]
    now=datetime.now(TZ); day=args.date or now.date(); stage=SCHEDULE[args.schedule] if args.schedule else args.stage
    output=args.output or (project/'artifacts/demo' if args.demo else project)
    if args.demo and output.resolve()==project: parser.error('Demo cannot write to production root')
    pipeline=Pipeline(project,output,'demo' if args.demo else 'live')
    if args.replay:
        result=read_json(pipeline.stage_path(day,stage))
        if result is None: parser.error('No stored snapshot; current APIs must not reconstruct old stages')
        print(json.dumps(result,ensure_ascii=False)); return
    if stage=='full_pipeline':
        if args.demo:
            if not pipeline.calendar.is_trading_day(day): day=pipeline.calendar.previous(day)
            previous=pipeline.calendar.previous(day); sequence=[(previous,'1600'),(previous,'2130')]+[(day,s) for s in STAGES]
        else:
            sequence=[(day,s) for s in STAGES if pipeline.config['stages'][s]['time']<=now.strftime('%H:%M')<=pipeline.config['stages'][s]['deadline']]
            if not sequence: sequence=[(day,'1600')]
    else: sequence=[(day,stage)]
    for d,s in sequence:
        result=pipeline.run(d,s,now)
        print(json.dumps({k:result.get(k) for k in ['run_id','date','stage','mode','status','candidate_count','data_quality','google_docs']},ensure_ascii=False))
    source=output/'data/latest/latest.json'
    if source.exists(): shutil.copyfile(source,project/('dashboard/data/demo.json' if args.demo else 'dashboard/data/latest.json'))
    if (output/'data/latest/run_status.json').exists() and not args.demo: shutil.copyfile(output/'data/latest/run_status.json',project/'dashboard/data/run_status.json')
    if not args.demo and result.get('status') in ('DEGRADED','MISSING_PREDECESSOR','CALENDAR_UNVERIFIED','OUTSIDE_STAGE_WINDOW'): raise SystemExit(2)
if __name__=='__main__': main()
