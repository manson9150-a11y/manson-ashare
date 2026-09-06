"""Explicit weekend initialization, separate from historical stage results."""
import argparse
import copy
import hashlib
import json
import uuid
from datetime import date, datetime
from pathlib import Path

from src.utils.calendar import TZ, stage_time
from src.utils.io import read_json, write_json, clean


def load_seed(root, day, as_of, calendar, config):
    seed = read_json(Path(root) / 'data/bootstrap' / f'{day}.json')
    if not seed:
        return None
    try:
        origin = seed['bootstrap_origin']
        observed = datetime.fromisoformat(seed['as_of_time'])
        market_day = calendar.previous(day)
        if (seed['mode'] != 'bootstrap' or seed['status'] != 'BOOTSTRAP_READY'
                or seed['data_quality']['status'] == 'RED'
                or origin['target_date'] != str(day) or seed['quote_date'] != str(market_day)
                or not market_day < observed.astimezone(TZ).date() < day
                or calendar.is_trading_day(observed.astimezone(TZ).date())
                or not observed < as_of <= stage_time(day, '0830', config)
                or origin['created_at'] != seed['as_of_time']):
            return None
        quotes = {q['code']: q for q in seed['quotes']}
        codes = {s['stock_code'] for group in seed['pools'].values() for s in group}
        if not codes or codes != set(quotes) or not codes <= set(seed['factors']):
            return None
        if any(datetime.fromisoformat(q['timestamp']).astimezone(TZ).date() != market_day
               or datetime.fromisoformat(q['timestamp']) > observed for q in quotes.values()):
            return None
        return seed
    except (KeyError, ValueError, TypeError):
        return None


def build(project, source_path, target, now=None):
    from src.pipeline import Pipeline
    now = now or datetime.now(TZ)
    project = Path(project)
    source = read_json(source_path)
    workspace = project / 'artifacts' / f'bootstrap-{target}'
    pipeline = Pipeline(project, workspace, mode='bootstrap')
    market_day = pipeline.calendar.previous(target)
    if (not pipeline.calendar.is_trading_day(target)
            or not market_day < now.date() < target or pipeline.calendar.is_trading_day(now.date())):
        raise ValueError('Initialization requires the weekend before the target trading day')
    if (source.get('mode') != 'retrospective' or source.get('status') != 'RETROSPECTIVE_COMPLETE'
            or source.get('quote_date') != str(market_day)
            or datetime.fromisoformat(source['finished_at']) > now
            or source['data_quality']['status'] == 'RED'):
        raise ValueError('A completed, already available close retrospective is required')
    # Apply evening pool rules now, then let the actual morning stage refresh events again.
    run = {'run_id': uuid.uuid4().hex, 'date': str(now.date()), 'stage': '2130',
           'stage_label': '周末初始化（实际生成时间见下方）', 'mode': 'bootstrap',
           'started_at': now.isoformat(), 'as_of_time': now.isoformat(), 'status': 'RUNNING',
           'warnings': ['周末初始化：按当前时点重新检查已保存收盘候选，不代表历史晚间任务已执行。']
                       + ['原始收盘复盘限制：' + w for w in source.get('warnings', [])],
           'errors': [], 'eliminations': [], 'pools': {}, 'data_quality': {}}
    origin = {'target_date': str(target), 'created_at': now.isoformat(),
              'market_date': str(market_day), 'source_run_id': source['run_id'],
              'source_sha256': hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
              'membership_observed_at': source['retrospective']['membership_observed_at'],
              'historical_risk_feed_verified': False,
              'scope': '仅首次隔夜确认可用；实际盘前刷新事件，继承事后分类和历史公告缺口。'}
    run['bootstrap_origin'] = origin
    pipeline.compute(run, market_day, '2130', now, copy.deepcopy(source))
    if run['status'] != 'COMPLETE':
        raise ValueError('Initialization data quality did not pass')
    run['status'] = 'BOOTSTRAP_READY'
    run['source_logs'] = pipeline.collector.logs + pipeline.announcements.logs
    run['finished_at'] = datetime.now(TZ).isoformat()
    run['candidate_count'] = sum(map(len, run['pools'].values()))
    keep = {s['stock_code'] for g in run['pools'].values() for s in g}
    run['quotes'] = [q for q in run['quotes'] if q['code'] in keep]
    run['factors'] = {k: v for k, v in run['factors'].items() if k in keep}
    for group in run['pools'].values():
        for s in group:
            s['date'] = str(now.date())
            s['rank_history'] = []
    path = project / 'data/bootstrap' / f'{target}.json'
    write_json(path, run)
    if load_seed(project, target, stage_time(target, '0730', pipeline.config), pipeline.calendar, pipeline.config) is None:
        raise ValueError('Generated initialization failed its eligibility check')
    from src.reports.render import stage_markdown
    report = project / 'reports/bootstrap' / f'{target}.md'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(stage_markdown(run), encoding='utf-8')
    return clean(run)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--target', required=True, type=date.fromisoformat)
    args = parser.parse_args()
    result = build(Path(__file__).resolve().parents[1], args.source, args.target)
    print(json.dumps({k: result[k] for k in ['status', 'candidate_count', 'as_of_time', 'bootstrap_origin']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
