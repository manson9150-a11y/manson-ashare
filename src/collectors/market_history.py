"""Validated free-source history, bounded incremental caches and market evidence.

Caches hold dated observations; they are never a substitute for a missing latest
trading session. Amount is a supplied currency value, never close times volume.
"""
from datetime import datetime, time
from pathlib import Path
import re
import statistics
import threading
import pandas as pd
from src.collectors.base import Unavailable
from src.models import SourceLog
from src.normalizers.quality import validate_bars
from src.utils.calendar import TZ
from src.utils.io import clean, read_json, write_json


class HistoryStore:
    def __init__(self, root, collector, config):
        self.root = Path(root) / 'data/cache/history'
        self.collector = collector
        self.config = config
        self._locks = {}
        self._lock = threading.Lock()

    def _record(self, frame, fallback=False):
        sources = sorted(set(frame.source.dropna().astype(str)))
        self.collector.logs.append(SourceLog(source_name='cache:' + '+'.join(sources),
            operation='history_cache', success=True, fetched_at=datetime.now(TZ).isoformat(),
            timestamp=frame.timestamp.iloc[-1].isoformat(), reliability_level=.8,
            fallback_priority=0, is_fallback=fallback, count=len(frame)).model_dump())

    def fetch(self, code, end, as_of, *, accept=None, quote=None, previous_trade_day=None, operation='history'):
        if not re.fullmatch(r'(?:(?:sh|sz|bj))?\d{6}', code):
            raise ValueError('invalid history symbol')
        key = operation + '_' + code
        with self._lock:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            return self._fetch(key, code, end, as_of, accept, quote, previous_trade_day, operation)

    def _fetch(self, key, code, end, as_of, accept, quote, previous_trade_day, operation):
        path = self.root / (key + '.parquet')
        metadata_path = path.with_suffix('.json')
        bars = self.config['sources']['history_bars']
        required = self.config['quality']['required_bars'] if operation == 'history' else 21

        def valid(frame):
            frame = validate_bars(frame, as_of, self.config)
            frame = frame[frame.timestamp.dt.tz_convert(TZ).dt.date <= end].copy()
            if len(frame) < required or frame.timestamp.iloc[-1].astimezone(TZ).date() != end:
                raise Unavailable('history short or stale')
            if 'amount' not in frame:
                frame['amount'] = None
            frame['amount'] = pd.to_numeric(frame.amount, errors='coerce')
            frame.loc[frame.amount < 0, 'amount'] = float('nan')
            if accept is not None:
                frame = accept(frame)
            return frame

        def has_amount(frame):
            return bool((frame.amount.tail(21).notna() & (frame.amount.tail(21) > 0)).all())

        cached = pd.DataFrame()
        if path.exists():
            try:
                metadata = read_json(metadata_path, {})
                if not metadata.get('as_of_time') or datetime.fromisoformat(metadata['as_of_time']) > as_of:
                    raise Unavailable('cache observed after requested cutoff')
                cached = pd.read_parquet(path)
                cached['timestamp'] = pd.to_datetime(cached.timestamp, utc=True)
                cached = cached[cached.timestamp <= as_of].sort_values('timestamp')
                cached = cached[cached.timestamp.dt.tz_convert(TZ).dt.date <= end]
                # A final quote can extend a consecutive, already complete series.
                # Never bridge missing trading sessions or append an intraday bar.
                if (quote is not None and previous_trade_day is not None and not cached.empty
                        and cached.timestamp.iloc[-1].astimezone(TZ).date() == previous_trade_day
                        and quote.code == code and quote.timestamp.astimezone(TZ).date() == end
                        and quote.timestamp.astimezone(TZ).time() >= time(15)
                        and quote.timestamp <= as_of and quote.volume > 0
                        and abs(cached.close.iloc[-1] / quote.previous_close - 1) * 100
                            <= self.config['quality']['conflict_price_pct']):
                    row = {'timestamp': quote.timestamp, 'open': quote.open, 'high': quote.high,
                        'low': quote.low, 'close': quote.price, 'volume': quote.volume,
                        'amount': quote.amount, 'source': quote.source}
                    cached = pd.concat([cached, pd.DataFrame([row])], ignore_index=True)
                candidate = valid(cached)
                if has_amount(candidate) or operation == 'index_history':
                    self._save(path, candidate.tail(bars), as_of)
                    self._record(candidate)
                    return candidate.tail(bars).reset_index(drop=True)
            except (ValueError, KeyError, Unavailable, OSError):
                pass

        partials = []
        # Good prices without supplied amount are held while all independent
        # providers are tried; a successful Tencent response cannot stop Sina.
        def accept_complete(frame):
            frame = valid(frame)
            if operation == 'history' and not has_amount(frame):
                partials.append(frame)
                raise Unavailable('amount history incomplete')
            return frame
        try:
            frame = self.collector.fetch(operation, code=code, end=end, accept=accept_complete)
        except Unavailable:
            if not partials:
                raise
            frame = max(partials, key=lambda f: f.amount.tail(21).notna().sum())
            frame.attrs['amount_status'] = 'UNAVAILABLE'
            self._record(frame, fallback=True)
        self._save(path, frame.tail(bars), as_of)
        return frame.tail(bars).reset_index(drop=True)

    @staticmethod
    def _save(path, frame, as_of):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.parquet.tmp')
        frame.to_parquet(temporary, index=False)
        temporary.replace(path)
        write_json(path.with_suffix('.json'), {'as_of_time': as_of.isoformat(),
            'fetched_at': datetime.now(TZ).isoformat(), 'adjustment': 'none', 'row_count': len(frame)})


def _status(key, label, status, reason, *, coverage=None, source=None, as_of=None):
    return {'id': key, 'label': label, 'status': status, 'reason': reason,
        'coverage': coverage, 'source': source, 'as_of_time': as_of, 'used_in_score': False}


def _archive_path(root, day):
    return Path(root) / 'data/cache/market_daily' / (str(day) + '.json')


def _load_archive(root, day, as_of):
    archive = read_json(_archive_path(root, day), {})
    if not archive:
        # A previously frozen full-market close can seed the rolling baseline.
        # This is a saved observation, not retrospective live data collection.
        for stage in ('2200', '1600'):
            saved = read_json(Path(root) / 'data/history' / day.strftime('%Y/%m/%d') / stage / 'stage_results.json', {})
            if (saved.get('status') != 'COMPLETE' or saved.get('quote_date') != str(day)
                    or saved.get('mode') != 'live' or saved.get('data_quality', {}).get('status') == 'RED'):
                continue
            market = saved.get('market', {})
            archive = {'trade_date': str(day), 'as_of_time': saved.get('as_of_time'),
                'amount': market.get('amount'), 'amount_quote_count': saved.get('valid_quote_count'),
                'quote_coverage': saved.get('data_quality', {}).get('coverage', 0),
                'limit_pool': saved.get('limit_pool', []),
                'limit_pool_complete': any(x.get('operation') == 'limit_pool' and x.get('success')
                    and x.get('source_name') == 'eastmoney' and x.get('count') ==
                        sum(r.get('source') == 'eastmoney' for r in saved.get('limit_pool', []))
                    for x in saved.get('source_logs', [])),
                'limit_pool_provider': 'eastmoney',
                'quotes': {q['code']: {'price': q['price'], 'change_pct': q['change_pct']}
                    for q in saved.get('quotes', [])}}
            break
    try:
        observed = datetime.fromisoformat(archive['as_of_time'])
        if archive.get('trade_date') != str(day) or observed > as_of or observed.tzinfo is None:
            return {}
    except (KeyError, TypeError, ValueError):
        return {}
    return archive


def build_market_context(quotes, limit_pool, collector, config, root, calendar, day, as_of, *, persist=False, limit_evidence=None, quality=None):
    context = {'trade_date': str(day), 'as_of_time': as_of.isoformat(), 'factor_statuses': [],
        'score_basis': '新增证据供研究参考，尚未加入市场规则分'}
    statuses = context['factor_statuses']
    by_code = {q.code: q for q in quotes if q.timestamp <= as_of and q.timestamp.astimezone(TZ).date() == day}
    is_close = bool(by_code) and all(q.timestamp.astimezone(TZ).time() >= time(15) for q in by_code.values())
    previous_day = calendar.previous(day)
    previous = _load_archive(root, previous_day, as_of)
    pool = {r['code']: r for r in limit_pool if r.get('trade_date') == str(day) and r.get('code') in by_code}
    vendor_pool = {c for c, r in pool.items() if r.get('source') == 'eastmoney'}
    vendor_complete = any(log.get('operation') == 'limit_pool' and log.get('success')
        and log.get('source_name') == 'eastmoney' and log.get('timestamp') == str(day)
        and log.get('count') == len(vendor_pool) and bool(vendor_pool) for log in collector.logs)
    context['limit_pool_scope'] = '供应商涨停池口径；与全市场涨跌停价格覆盖分开展示'
    context['limit_pool_complete'] = vendor_complete

    # Broken boards are provider-scoped counts, not sums of individual break events.
    try:
        broken = collector.fetch('broken_pool', day=day)
        broken_codes = {r['code'] for r in broken if r.get('trade_date') == str(day)}
        if not vendor_complete or not broken_codes:
            raise Unavailable('compatible limit pool unavailable')
        broken_codes -= vendor_pool
        denominator = len(broken_codes | vendor_pool)
        context['break_rate'] = len(broken_codes) / denominator if denominator else None
        context['broken_count'] = len(broken_codes)
        context['touched_limit_count'] = denominator
        context['break_rate_basis'] = '收盘未封板股票数 / (收盘涨停股票数 + 收盘未封板股票数)，东方财富池口径' if is_close else '当前未封板股票数 / 当前触板股票数，盘中值'
        statuses.append(_status('break_rate', '炸板率', 'AVAILABLE', context['break_rate_basis'],
            coverage=1, source='eastmoney', as_of=as_of.isoformat()))
    except Unavailable:
        known = [q for q in by_code.values() if q.limit_up_price is not None and q.limit_up_price > q.previous_close]
        touched = [q for q in known if q.high >= q.limit_up_price - .0051]
        opened = [q for q in touched if abs(q.price - q.limit_up_price) > .0051]
        coverage = len(known) / len(by_code) if by_code else 0
        context.update(break_rate=len(opened) / len(touched) if touched else None,
            broken_count=len(opened) if touched else None, touched_limit_count=len(touched) if touched else None,
            break_rate_basis='具有明确涨停价的行情样本；未覆盖特殊制度及缺价格股票')
        statuses.append(_status('break_rate', '炸板率', 'PARTIAL' if touched else 'UNAVAILABLE',
            context['break_rate_basis'], coverage=coverage, source='explicit_quote_limit_price', as_of=as_of.isoformat()))

    # Every previous-day member remains in the denominator; missing quotes never
    # silently disappear from premium/negative-return/promotions coverage.
    old_pool = {r['code']: r for r in previous.get('limit_pool', []) if r.get('source') == 'eastmoney'}
    tracked = [by_code[c] for c in old_pool if c in by_code]
    coverage = len(tracked) / len(old_pool) if old_pool else 0
    context['yesterday_limit_up'] = {'trade_date': str(previous_day), 'sample_count': len(old_pool),
        'observed_count': len(tracked), 'coverage': coverage,
        'mean_return_pct': statistics.mean(q.change_pct for q in tracked) if tracked else None,
        'median_return_pct': statistics.median(q.change_pct for q in tracked) if tracked else None,
        'negative_fraction': sum(q.change_pct < 0 for q in tracked) / len(tracked) if tracked else None,
        'basis': '上一交易日已归档供应商涨停名单，当日行情涨跌幅等权（供应商昨收口径，除权日不等同裸价格收益）；含缺失样本覆盖率'}
    premium_status = 'AVAILABLE' if tracked and coverage == 1 and previous.get('limit_pool_complete') else 'PARTIAL' if tracked else 'UNAVAILABLE'
    statuses.append(_status('yesterday_premium', '昨日涨停溢价', premium_status,
        '需要严格上一交易日涨停归档及当日行情；当前为已跟踪名单等权涨跌幅', coverage=coverage,
        source='saved_limit_pool+quotes', as_of=as_of.isoformat()))
    promotions = {}
    for level in (1, 2, 3):
        names = [c for c, r in old_pool.items() if r.get('board_count') == level]
        current = [c for c in names if c in by_code]
        promoted = [c for c in current if pool.get(c, {}).get('board_count') == level + 1]
        known_boards = [c for c in current if c not in pool or pool[c].get('board_count') is not None]
        verified = bool(names) and vendor_complete and previous.get('limit_pool_complete') and len(known_boards) == len(names)
        promotions[str(level) + '_to_' + str(level + 1)] = {'base_count': len(names), 'observed_count': len(current),
            'promoted_count': len(promoted) if verified else None, 'rate': len(promoted) / len(names) if verified else None,
            'status': 'AVAILABLE' if verified else 'NO_SAMPLE' if not names else 'UNAVAILABLE'}
    context['promotion'] = promotions
    has_promotion = any(v['rate'] is not None for v in promotions.values())
    statuses.append(_status('promotion', '1进2/2进3/3进4晋级率',
        'AVAILABLE' if has_promotion and previous.get('limit_pool_complete') else 'PARTIAL' if has_promotion else 'UNAVAILABLE',
        '按上一交易日供应商连板层级追踪；无分母显示无样本，不补零', coverage=coverage,
        source='saved_limit_pool+current_limit_pool', as_of=as_of.isoformat()))
    high_names = [c for c, r in old_pool.items() if (r.get('board_count') or 0) >= 3]
    high_quotes = [by_code[c] for c in high_names if c in by_code]
    high_coverage = len(high_quotes) / len(high_names) if high_names else 0
    context['high_board_loss'] = {'minimum_board_count': 3, 'sample_count': len(high_names), 'observed_count': len(high_quotes),
        'mean_return_pct': statistics.mean(q.change_pct for q in high_quotes) if high_quotes else None,
        'negative_fraction': sum(q.change_pct < 0 for q in high_quotes) / len(high_quotes) if high_quotes else None,
        'coverage': high_coverage}
    statuses.append(_status('high_board_loss', '高位股亏钱效应',
        'AVAILABLE' if high_quotes and high_coverage == 1 and previous.get('limit_pool_complete') else 'PARTIAL' if high_quotes else 'UNAVAILABLE',
        '上一交易日至少3连板股票的当日等权涨跌幅及下跌占比；没有样本时不推断情绪',
        coverage=high_coverage, source='saved_limit_pool+quotes', as_of=as_of.isoformat()))

    # Full-day totals are comparable only to complete previous trading sessions.
    amounts = []
    cursor = day
    for _ in range(20):
        cursor = calendar.previous(cursor)
        archive = _load_archive(root, cursor, as_of)
        if archive.get('amount') is None or (archive.get('quote_coverage') or 0) < .98:
            break
        amounts.append(archive['amount'])
    amount = sum(q.amount for q in by_code.values()) if by_code else None
    full_coverage = (quality or {}).get('coverage')
    comparable = is_close and full_coverage is not None and full_coverage >= .98
    ratios = {'current_amount': amount, 'history_days': len(amounts), 'basis': '行情覆盖至少98%的收盘成交额 / 前N个同口径交易日均值，不含当天'}
    for window in (5, 10, 20):
        mean = statistics.mean(amounts[:window]) if len(amounts) >= window else None
        ratios['mean_' + str(window) + 'd'] = mean
        ratios['ratio_' + str(window) + 'd'] = amount / mean if comparable and amount is not None and mean and mean > 0 else None
    context['market_amount'] = ratios
    statuses.append(_status('market_amount', '成交额相对5/10/20日均值',
        'AVAILABLE' if comparable and len(amounts) >= 20 else 'PARTIAL' if comparable and len(amounts) >= 5 else 'UNAVAILABLE',
        f'已积累{len(amounts)}个连续完整收盘交易日；午间缺同时间基准不作全日比较',
        coverage=min(len(amounts) / 20, 1) if is_close else 0, source='saved_full_market_close', as_of=as_of.isoformat()))

    indices = []
    store = HistoryStore(root, collector, config)
    index_day = day if is_close else previous_day
    for code, name in [('sh000001', '上证指数'), ('sz399001', '深证成指'), ('sz399006', '创业板指')]:
        try:
            frame = store.fetch(code, index_day, as_of, operation='index_history')
            close = frame.close.astype(float)
            row = {'code': code, 'name': name, 'trade_date': str(index_day), 'close': float(close.iloc[-1]),
                'source': str(frame.source.iloc[-1])}
            for window in (5, 10, 20):
                average = close.tail(window).mean()
                row['ma' + str(window)] = float(average)
                row['return_' + str(window) + 'd'] = float((close.iloc[-1] / close.iloc[-window - 1] - 1) * 100)
                row['above_ma' + str(window)] = bool(close.iloc[-1] > average)
            indices.append(row)
        except Unavailable:
            continue
    context['indices'] = indices
    statuses.append(_status('index_trend', '指数5/10/20日趋势', 'AVAILABLE' if len(indices) == 3 else 'PARTIAL' if indices else 'UNAVAILABLE',
        '三大指数独立日线；午间沿用前收盘趋势并标交易日', coverage=len(indices) / 3,
        source='+'.join(sorted({x['source'] for x in indices})) or None, as_of=as_of.isoformat()))

    if persist and is_close and len(by_code) >= config['sources']['expected_universe_min']:
        # Only the limit cohort needs its own rows; full quotes remain in the
        # existing daily parquet archive. A daily cache is normally <50KB.
        archive = {'trade_date': str(day), 'as_of_time': as_of.isoformat(), 'amount': amount,
            'amount_quote_count': len(by_code), 'quote_coverage': full_coverage,
            'limit_pool': list(pool.values()), 'limit_pool_complete': vendor_complete,
            'limit_pool_provider': 'eastmoney',
            'quotes': {c: {'price': by_code[c].price, 'change_pct': by_code[c].change_pct} for c in pool}}
        write_json(_archive_path(root, day), archive)
    return clean(context)
