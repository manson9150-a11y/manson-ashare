from datetime import datetime, time
from src.utils.calendar import TZ


def validate_quotes(quotes, as_of, expected_date, config, stage, universe_count=None):
    accepted, rejected, conflicts = {}, [], []
    for q in quotes:
        reason = None
        timestamp = q.timestamp.astimezone(TZ)
        if q.timestamp > as_of:
            reason = 'FUTURE_QUOTE'
        elif timestamp.date() != expected_date:
            reason = 'STALE_TRADING_DATE'
        elif q.cached:
            reason = 'HISTORICAL_CACHE'
        elif q.suspended or q.volume == 0 or q.open == 0:
            reason = 'SUSPENDED_OR_NO_TRADE'
        elif q.high < max(q.open, q.price) or q.low > min(q.open, q.price) or q.low > q.high:
            reason = 'INVALID_OHLC'
        elif abs(q.change_pct) > config['quality']['max_abs_change_pct']:
            reason = 'EXTREME_VALUE_OR_CORPORATE_ACTION'
        elif abs((q.price / q.previous_close - 1) * 100 - q.change_pct) > config['quality']['conflict_price_pct']:
            reason = 'PRICE_CHANGE_CONFLICT'
        elif stage == '1135' and not time(11, 30) <= timestamp.time() <= time(11, 35):
            reason = 'NOT_MORNING_CLOSE'
        elif stage in ('1600', '2130', '0730', '0830') and timestamp.time() < time(15, 0):
            reason = 'NOT_SESSION_CLOSE'
        if reason:
            rejected.append({'code': q.code, 'reason': reason, 'timestamp': q.timestamp.isoformat()})
            continue
        old = accepted.get(q.code)
        if old:
            if abs(q.price / old.price - 1) * 100 > config['quality']['conflict_price_pct']:
                conflicts.append(q.code)
            if (q.reliability >= 0.99, q.timestamp, q.reliability) <= (old.reliability >= 0.99, old.timestamp, old.reliability):
                continue
        accepted[q.code] = q
    coverage = len(accepted) / max(universe_count or len(quotes), 1)
    status = 'GREEN'
    if not accepted or coverage < config['sources']['min_market_coverage']:
        status = 'RED'
    elif rejected or conflicts or any(q.fallback for q in accepted.values()):
        status = 'YELLOW'
    return list(accepted.values()), {'status': status, 'coverage': round(coverage, 4), 'accepted': len(accepted), 'rejected': rejected, 'conflicts': conflicts, 'expected_trade_date': str(expected_date), 'as_of_time': as_of.isoformat()}


def validate_bars(frame, as_of, config):
    import pandas as pd
    if frame.empty:
        return frame
    df = frame.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df[df.timestamp <= as_of].sort_values('timestamp')
    df = df.drop_duplicates('timestamp', keep='last')
    required = ['open', 'high', 'low', 'close', 'volume']
    df[required] = df[required].apply(pd.to_numeric, errors='coerce')
    df = df.dropna(subset=required)
    df = df[(df.close > 0) & (df.open > 0) & (df.volume >= 0) & (df.low > 0)]
    df = df[(df.high >= df[['open', 'close']].max(axis=1)) & (df.low <= df[['open', 'close']].min(axis=1))]
    # Unadjusted series: unverified discontinuities are rejected, never silently bridged.
    if (df.close.pct_change().abs() * 100 > config['quality']['max_abs_change_pct']).any():
        return df.iloc[:0]
    return df.reset_index(drop=True)
