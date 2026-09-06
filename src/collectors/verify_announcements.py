"""Live read-only source check, with isolated artifacts and no report writes."""
import json
from datetime import datetime
from pathlib import Path

from src.pipeline import Pipeline
from src.utils.calendar import TZ
from src.utils.io import read_json, write_json


def main():
    project = Path(__file__).resolve().parents[2]
    output = project / 'artifacts/announcement-verification'
    p = Pipeline(project, output)
    seed = read_json(project / 'data/bootstrap/2026-09-07.json')
    codes = [s['stock_code'] for group in seed['pools'].values() for s in group]
    result = {'checked_at': datetime.now(TZ).isoformat(), 'requested_stocks': len(codes)}
    try:
        events = p.announcements.fetch('events', codes=codes)
        result.update(status='PASS', source=next(log['source_name'] for log in p.announcements.logs if log['success']),
                      announcements=len(events), stocks_with_announcements=len({e.stock_code for e in events}),
                      date_only=sum(e.publish_time_precision == 'date' for e in events))
        write_json(output / 'events.json', [e.model_dump(mode='json') for e in events])
    except Exception as exc:
        result.update(status='FAIL', error_type=type(exc).__name__)
    result['source_logs'] = p.announcements.logs
    write_json(output / 'verification.json', result)
    print(json.dumps(result, ensure_ascii=False))
    if result['status'] != 'PASS':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
