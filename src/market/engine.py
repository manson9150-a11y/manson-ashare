import statistics

MISSING = ['炸板率', '昨日涨停溢价', '首板/连板梯队', '1进2/2进3/3进4晋级率', '最高板高度/梯队完整度', '成交额相对5/10/20日均值', '指数5/10/20日趋势', '高位股亏钱效应', '短线情绪周期', '主力资金', '外部市场']

def market_score(quotes, config, quality):
    if not quotes or quality['status'] == 'RED':
        return {'score': None, 'environment': None, 'basis': 'INSUFFICIENT_DATA', 'missing_factors': MISSING + ['可靠全市场覆盖']}
    changes = [q.change_pct for q in quotes]
    up, down = sum(x > 0 for x in changes), sum(x < 0 for x in changes)
    breadth = up / len(changes)
    median = statistics.median(changes)
    w = config['market']['weights']
    score = round(max(0, min(100, breadth * 100 * w['breadth'] + max(0, min(100, 50 + median * config['market']['median_scale'])) * w['median_return'])), 2)
    limits_up = [q for q in quotes if q.limit_up_price is not None and abs(q.price - q.limit_up_price) < 0.0051]
    limits_down = [q for q in quotes if q.limit_down_price is not None and abs(q.price - q.limit_down_price) < 0.0051]
    has_limits = any(q.limit_up_price is not None for q in quotes)
    return {'score': score, 'environment': '强' if score >= config['market']['strong_threshold'] else '正常' if score >= config['market']['weak_threshold'] else '偏弱', 'basis': 'BREADTH_MVP', 'up': up, 'down': down, 'flat': len(changes)-up-down, 'breadth': breadth, 'median_return': median, 'amount': sum(q.amount for q in quotes), 'limit_up_count': len(limits_up) if has_limits else None, 'limit_down_count': len(limits_down) if has_limits else None, 'missing_factors': MISSING}
