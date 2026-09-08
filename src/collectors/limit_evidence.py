"""Explicit price evidence first; conservative, labelled exchange-rule fallback."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from src.utils.calendar import TZ


def rate_for(q):
    # Never infer exceptional securities, IPO/relisting sessions or risk warnings.
    name = q.name.upper().replace(' ', '')
    if any(x in name for x in ('ST', '退')) or name.startswith(('N', 'C')):
        return None
    if q.code.startswith(('688', '300', '301')):
        return Decimal('0.20')
    if q.code.startswith(('600', '601', '603', '605', '000', '001', '002', '003')):
        return Decimal('0.10')
    return None  # Beijing and unknown markets need explicit vendor evidence.


def upper_price(previous, rate):
    return float((Decimal(str(previous)) * (1 + rate)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def near_limit(q):
    rate = rate_for(q)
    if rate is None or q.suspended or q.volume <= 0:
        return False
    target = q.limit_up_price or upper_price(q.previous_close, rate)
    return q.price >= target - 0.011


def enrich_limits(quotes, factors, vendor_rows, day, calendar):
    """Never equate an unvalidated empty pool with a verified zero-limit market."""
    by_code = {q.code: q for q in quotes}
    rows = {}
    rejected = []
    for item in vendor_rows:
        q = by_code.get(item.get('code'))
        if (not q or item.get('trade_date') != str(day)
                or q.timestamp.astimezone(TZ).date() != day
                or q.suspended or q.volume <= 0):
            rejected.append(item.get('code'))
            continue
        # Pool identity alone must not resurrect an opened board or stale price.
        target = item.get('limit_up_price') or q.limit_up_price
        if target is None or abs(q.price - target) > .0051:
            rejected.append(q.code)
            continue
        rows[q.code] = {**item, 'limit_up_price': target, 'identity_basis': 'vendor_limit_price'}
    known = 0
    derived = 0
    for q in quotes:
        if q.timestamp.astimezone(TZ).date() != day or q.suspended or q.volume <= 0:
            continue
        explicit = q.limit_up_price
        if explicit is not None and explicit > q.previous_close and q.high <= explicit + .0051:
            known += 1
            if abs(q.price - explicit) <= .0051:
                rows.setdefault(q.code, {'code': q.code, 'trade_date': str(day),
                    'source': q.source, 'identity_basis': 'vendor_limit_price',
                    'limit_up_price': explicit, 'board_count': None})
        f = factors.get(q.code, {})
        bars = f.get('bars', [])
        rate = rate_for(q)
        if rate is None or len(bars) < 61:
            continue
        last = bars[-1]
        # Require the matching final bar and unadjusted previous-close continuity.
        if (str(last['timestamp'])[:10] != str(day)
                or abs(last['close'] - q.price) > .0051
                or abs(bars[-2]['close'] - q.previous_close) > .0051):
            continue
        target = upper_price(q.previous_close, rate)
        if q.high > target + .0051 or q.low < upper_price(q.previous_close, -rate) - .0051:
            continue
        if explicit is None:
            known += 1
        if abs(q.price - target) > .0051:
            continue
        if q.code not in rows:
            rows[q.code] = {'code': q.code, 'trade_date': str(day), 'source': 'exchange_rule+daily_bars',
                'identity_basis': 'rule_derived_not_vendor_confirmed', 'limit_up_price': target,
                'board_count': None, 'risk_note': '规则推导；未覆盖特殊复牌及完整历史除权事件，不能视作官方涨停池。'}
            derived += 1
        # Trailing close pattern is supplementary evidence, not an invented official ladder.
        count = 0
        for i in range(len(bars) - 1, 0, -1):
            current, before = bars[i], bars[i-1]
            d = datetime.fromisoformat(str(current['timestamp'])).date()
            prev = datetime.fromisoformat(str(before['timestamp'])).date()
            if calendar.previous(d) != prev:
                break
            cap = upper_price(before['close'], rate)
            if (current.get('volume', 0) <= 0 or abs(current['close'] - cap) > .0051
                    or current['high'] > cap + .0051):
                break
            count += 1
        rows[q.code]['derived_board_count'] = count or None
        rows[q.code]['board_count_basis'] = 'vendor' if rows[q.code].get('board_count') else 'UNKNOWN; see derived_board_count'
    return list(rows.values()), {'status': 'PARTIAL' if known < len(quotes) else 'AVAILABLE',
        'quote_count': len(quotes), 'price_evidence_count': known, 'identified': len(rows),
        'rule_derived': derived, 'rejected_vendor_rows': rejected,
        'note': '供应商证据与规则推导分别标注；未识别不等于未涨停。'}
