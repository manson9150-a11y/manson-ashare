import statistics
from collections import Counter

MISSING = ['炸板率', '昨日涨停溢价', '首板/连板梯队', '1进2/2进3/3进4晋级率', '最高板高度/梯队完整度', '成交额相对5/10/20日均值', '指数5/10/20日趋势', '高位股亏钱效应', '短线情绪周期', '主力资金', '外部市场']
CONTEXT_LABELS = {'break_rate': '炸板率', 'yesterday_premium': '昨日涨停溢价',
    'promotion': '1进2/2进3/3进4晋级率', 'market_amount': '成交额相对5/10/20日均值',
    'index_trend': '指数5/10/20日趋势', 'high_board_loss': '高位股亏钱效应'}


def market_score(quotes, config, quality, limit_pool=None, context=None):
    missing = list(MISSING)
    context = context or {}
    if not quotes or quality['status'] == 'RED':
        return {'score': None, 'environment': None, 'basis': 'INSUFFICIENT_DATA',
            'missing_factors': missing + ['可靠全市场覆盖'], 'context': context}
    changes = [q.change_pct for q in quotes]
    up, down = sum(x > 0 for x in changes), sum(x < 0 for x in changes)
    breadth = up / len(changes)
    median = statistics.median(changes)
    w = config['market']['weights']
    score = round(max(0, min(100, breadth * 100 * w['breadth'] + max(0, min(100, 50 + median * config['market']['median_scale'])) * w['median_return'])), 2)
    limits_up = [q for q in quotes if q.limit_up_price is not None and abs(q.price - q.limit_up_price) < 0.0051]
    limits_down = [q for q in quotes if q.limit_down_price is not None and abs(q.price - q.limit_down_price) < 0.0051]
    up_coverage = sum(q.limit_up_price is not None for q in quotes) / len(quotes)
    down_coverage = sum(q.limit_down_price is not None for q in quotes) / len(quotes)
    by_code = {q.code: q for q in quotes}
    pool = {}
    for item in limit_pool or []:
        q = by_code.get(item.get('code'))
        target = item.get('limit_up_price')
        if (q is not None and item.get('trade_date') == str(q.timestamp.date())
                and target is not None and abs(q.price - target) < .0051):
            pool[q.code] = item
    boards = Counter(r['board_count'] for r in pool.values()
        if type(r.get('board_count')) is int and r['board_count'] > 0)
    board_coverage = sum(boards.values()) / len(pool) if pool else 0
    if boards:
        missing.remove('首板/连板梯队')
        missing.remove('最高板高度/梯队完整度')
        if board_coverage < 1:
            missing.append('完整供应商连板层级覆盖')
    for status in context.get('factor_statuses', []):
        label = CONTEXT_LABELS.get(status.get('id'))
        if status.get('status') == 'AVAILABLE' and label in missing:
            missing.remove(label)
    if min(up_coverage, down_coverage) < 1:
        missing.append('全市场涨跌停价覆盖')
    return {'score': score, 'environment': '强' if score >= config['market']['strong_threshold'] else '正常' if score >= config['market']['weak_threshold'] else '偏弱',
        'basis': 'BREADTH_MVP', 'score_basis_label': '上涨占比 + 涨跌幅中位数；新增市场证据尚未纳入评分',
        'up': up, 'down': down, 'flat': len(changes)-up-down, 'breadth': breadth,
        'median_return': median, 'amount': sum(q.amount for q in quotes),
        'limit_up_count': len(limits_up) if up_coverage == 1 else None,
        'limit_down_count': len(limits_down) if down_coverage == 1 else None,
        'known_limit_up_count': len({q.code for q in limits_up} | set(pool)),
        'known_limit_down_count': len(limits_down),
        'limit_up_price_coverage': up_coverage, 'limit_down_price_coverage': down_coverage,
        'limit_pool_count': len(pool), 'first_board_count': boards.get(1, 0) if boards else None,
        'consecutive_board_count': sum(v for k, v in boards.items() if k >= 2) if boards else None,
        'highest_board': max(boards) if boards else None,
        'board_ladder': {str(k): v for k, v in sorted(boards.items())},
        'board_count_coverage': board_coverage,
        'board_ladder_basis': '独立涨停名单中的供应商板数；不把推导板数混入供应商梯队',
        'context': context, 'missing_factors': missing}
