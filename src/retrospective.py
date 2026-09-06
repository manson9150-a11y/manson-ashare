"""Explicit retrospective close scan; never fills production point-in-time history."""
import argparse
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src.collectors.base import Unavailable
from src.models import Quote
from src.pipeline import Pipeline
from src.utils.calendar import TZ
from src.utils.io import clean, read_json, write_json


class FrozenCollector:
    def __init__(self, collector, raw, day):
        self.collector, self.raw, self.day = collector, Path(raw), day
        self.raw.mkdir(parents=True, exist_ok=True)
        self.logs = read_json(self.raw / 'capture_logs.json', [])
        self.logs += [log for log in read_json(self.raw / 'source_logs.json', [])
                      if log['operation'] in ('history', 'limit_pool')]

    def fetch(self, operation, accept=None, **kwargs):
        if operation == 'history':
            if kwargs['end'] != self.day:
                raise ValueError('Historical cutoff mismatch')
            path = self.raw / 'history' / (kwargs['code'] + '.parquet')
        else:
            path = self.raw / (operation + '.json')
        if path.exists():
            if operation == 'history':
                result = pd.read_parquet(path)
            else:
                result = read_json(path)['rows']
                if operation == 'quotes':
                    result = [Quote.model_validate(q) for q in result]
        else:
            result = self.collector.fetch(operation, **kwargs)
            path.parent.mkdir(parents=True, exist_ok=True)
            if operation == 'history':
                result.to_parquet(path, index=False)
            else:
                rows = [q.model_dump(mode='json') for q in result] if operation == 'quotes' else result
                write_json(path, {'observed_at': datetime.now(TZ).isoformat(), 'rows': rows})
        if accept:
            result = accept(result)
        return result


class NoRetrospectiveAnnouncements:
    logs = []

    def fetch(self, *args, **kwargs):
        # A present-day announcement listing is not a frozen historical risk feed.
        raise Unavailable('Historical announcement snapshots unavailable')


class RetrospectivePipeline(Pipeline):
    def __init__(self, project, output, day, membership_path):
        project, output = Path(project).resolve(), Path(output).resolve()
        if output == project or project in output.parents and 'artifacts' not in output.relative_to(project).parts:
            raise ValueError('Retrospective output must be isolated from production data')
        super().__init__(project, output, mode='retrospective')
        self.day = day
        self.membership_snapshot = read_json(membership_path)
        if not self.membership_snapshot or not self.membership_snapshot.get('observed_at'):
            raise ValueError('Timestamped membership snapshot required')
        self.collector = FrozenCollector(self.collector, output / 'raw', day)
        self.announcements = NoRetrospectiveAnnouncements()
        self.config['ai']['enabled'] = False

    def run(self, day, stage='1600', now=None):
        if stage != '1600' or day != self.day:
            raise ValueError('Retrospective mode only supports the specified close scan')
        now = now or datetime.now(TZ)
        if day >= now.astimezone(TZ).date():
            raise ValueError('Retrospective date must be in the past')
        return super().run(day, stage, now)

    def membership(self, quotes, as_of):
        return self.membership_snapshot['sectors']

    def compute(self, run, day, stage, as_of, previous):
        # This is an end-of-day reconstruction, not a replay of the 16:00
        # information set. Keep the original stage time separate from provider
        # updates received later on the same market date.
        original_cutoff = as_of
        as_of = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=TZ)
        run['as_of_time'] = as_of.isoformat()
        run['stage_label'] = '收盘复盘（含当日盘后补齐）'
        run.pop('scheduled_for', None)
        run['retrospective'] = {
            'market_date': str(day),
            'original_stage_time': original_cutoff.isoformat(),
            'availability_cutoff': as_of.isoformat(),
            'quote_basis': '目标交易日收盘数据，允许同日盘后接口更新，不模拟16:00即时可用性',
            'computed_at': run['started_at'],
            'membership_observed_at': self.membership_snapshot['observed_at'],
            'membership_is_historical': False,
            'historical_universe_verified': False,
            'historical_risk_feed_verified': False,
            'not_a_point_in_time_backtest': True,
        }
        run['warnings'] += [
            '历史收盘复盘：使用目标交易日收盘行情，允许同日16:00后的接口更新；不是16:00即时信号回测，后续交易日数据不纳入。',
            f"经用户选择使用现有行业分类，采集时间 {self.membership_snapshot['observed_at']}；当时的成分、上市范围和名称状态未完整核验。",
            '当时盘前、午盘、晚间资讯与风险公告快照缺失，不能重建五阶段名单变化；独立催化和公告硬风险无法完整复核。',
            '沿用当前规则与250只历史日线预算；未改变评分门槛、位置分类或ATR规则。',
        ]
        super().compute(run, day, stage, as_of, previous)
        self.collector.logs += self.collector.collector.logs
        write_json(self.output / 'raw' / 'source_logs.json', self.collector.logs)
        if run['status'] == 'COMPLETE':
            run['status'] = 'RETROSPECTIVE_COMPLETE'
        for group in run['pools'].values():
            for stock in group:
                stock['negative_factor'] += '；历史公告硬风险及当时板块归属未完整核验'
                stock['rank_history'] = []
        missing_amount = sum(f.get('amount_ratio_5d') is None for f in run.get('factors', {}).values())
        run['data_quality']['missing_amount_history_count'] = missing_amount
        if missing_amount:
            run['warnings'].append(f'{missing_amount}只股票缺少成交额历史：量价分留空并按既有规则重分配权重，不能确认放量启动或缩量回调。')
        if not run.get('limit_pool'):
            run['warnings'].append('历史涨停池没有可用明细；仅使用行情源明确给出的涨停价识别封板，连板数、封单和炸板质量留空。')
        run['pool_notes'] = {
            'POOL_A': '涨停价和封板明细覆盖不足，未确认可用接力候选；不代表当天零涨停。',
            'POOL_B': '现有行业分类下的收盘技术规则候选；历史公告风险未完整核验。',
            'POOL_C': '缺少当时已核验的独立催化证据，暂不输出此池候选。',
        }
        if run['market'].get('limit_up_price_coverage') == 1:
            limit_quotes = [q for q in run.get('quotes', []) if q.get('limit_up_price') is not None
                            and abs(q['price'] - q['limit_up_price']) < 0.0051]
            ready = sum(q['code'] in run.get('factors', {}) for q in limit_quotes)
            run['limit_scan'] = {'identified_limit_up': len(limit_quotes), 'history_ready': ready}
            run['pool_notes']['POOL_A'] = f'识别封板{len(limit_quotes)}只，其中{ready}只具备本轮技术因子；其余受板块映射或250只日线预算限制。连板数、封单质量仍待核验。'
        for sector in run.get('sectors', []):
            sector['history'] = {'1600': sector['score']}
        run['missing_factors'] += ['历史成分和证券状态快照', '历史公告硬风险完整核验', '盘前及午盘时点快照']

    def finish(self, run):
        result = super().finish(run)
        # Keep a separate, directly viewable report without pretending missing stages ran.
        report = self.output / 'reports' / f'{self.day}-close-retrospective.md'
        source = self.stage_path(self.day, '1600').parent / 'report.md'
        report.write_text('# ' + str(self.day) + ' 收盘规则复盘\n\n' + source.read_text(), encoding='utf-8')
        write_json(self.output / 'raw' / 'membership.json', self.membership_snapshot)
        write_json(self.output / 'rules.json', self.config)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True, type=date.fromisoformat)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--membership', required=True, type=Path)
    parser.add_argument('--allow-current-membership', action='store_true', required=True,
                        help='Explicitly acknowledge retrospective membership and universe limitations')
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    result = RetrospectivePipeline(project, args.output, args.date, args.membership).run(args.date)
    summary = {k: result.get(k) for k in ['date', 'status', 'candidate_count', 'market', 'funnel', 'data_quality']}
    write_json(args.output / 'summary.json', summary)
    print(__import__('json').dumps(clean(summary), ensure_ascii=False), flush=True)
    if result['status'] != 'RETROSPECTIVE_COMPLETE':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
