import numpy as np
import pandas as pd
from src.utils.io import clean


def wilder_atr(frame, period=14):
    previous = frame.close.shift(1)
    tr = pd.concat([frame.high - frame.low, (frame.high - previous).abs(), (frame.low - previous).abs()], axis=1).max(axis=1)
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    if len(tr) >= period:
        result.iloc[period - 1] = tr.iloc[:period].mean()
        for i in range(period, len(tr)):
            result.iloc[i] = (result.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period
    return result


def technical(frame, period=14):
    if frame.empty:
        return {}
    c = frame.close.astype(float)
    last = float(c.iloc[-1])
    out = {'price': last, 'bars_count': len(frame)}
    amounts = pd.to_numeric(frame.get('amount', pd.Series(index=frame.index, dtype=float)), errors='coerce')
    amounts = amounts.where(amounts >= 0)
    out['amount_history_coverage'] = float(amounts.tail(21).notna().mean())
    out['amount_history_status'] = 'AVAILABLE' if len(amounts) >= 21 and amounts.tail(21).notna().all() else 'PARTIAL' if amounts.notna().any() else 'UNAVAILABLE'
    for n in [5, 10, 20, 60]:
        ma = c.rolling(n).mean()
        out[f'ma{n}'] = ma.iloc[-1]
        out[f'distance_ma{n}'] = (last / ma.iloc[-1] - 1) * 100
        out[f'slope_ma{n}'] = (ma.iloc[-1] / ma.iloc[-2] - 1) * 100 if len(c) > n else None
    for n in [1, 3, 5, 10, 20]:
        out[f'return_{n}d'] = (last / c.iloc[-n - 1] - 1) * 100 if len(c) > n else None
    for n in [5, 10, 20]:
        # Baseline excludes current bar to avoid self-dilution.
        mean = amounts.shift(1).rolling(n).mean().iloc[-1]
        out[f'amount_mean_{n}d'] = mean
        out[f'amount_ratio_{n}d'] = amounts.iloc[-1] / mean if mean > 0 else None
    atr = wilder_atr(frame, period).iloc[-1]
    out['atr'] = atr
    out['natr'] = atr / last * 100
    out['move_atr'] = abs(out['return_1d']) / out['natr'] if out['natr'] > 0 and out['return_1d'] is not None else None
    out['bull_alignment'] = bool(out['ma5'] > out['ma10'] > out['ma20'])
    out['new_high_5d'] = bool(last > frame.high.iloc[-6:-1].max())
    out['new_high_20d'] = bool(last > frame.high.iloc[-21:-1].max())
    out['breakout'] = out['new_high_20d']
    out['consecutive_up_2'] = bool((c.diff().iloc[-2:] > 0).all())
    out['consecutive_up_3'] = bool((c.diff().iloc[-3:] > 0).all())
    return clean(out)
