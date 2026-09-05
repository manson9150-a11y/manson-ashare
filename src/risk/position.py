def classify(f, sector, config, hard_risk=False):
    p=config['position']
    needed=['ma20','slope_ma20','return_5d','return_20d','distance_ma20','move_atr']
    if hard_risk or any(f.get(k) is None for k in needed):
        return '排除', '重大事件风险或核心历史因子不足'
    ratio=f.get('amount_ratio_5d')
    if sector.get('state')=='转弱/退潮' or f['slope_ma20']<p['exclude']['min_slope_ma20']:
        return '排除','板块退潮或MA20趋势向下'
    if f['return_20d']>p['exclude']['max_return_20d']:
        return '排除','累计涨幅严重透支'
    if f['distance_ma20']<p['exclude']['breakdown_distance'] and ratio is not None and ratio>p['exclude']['breakdown_volume']:
        return '排除','放量破位'
    if f['return_20d']>p['high']['return_20d'] or f['return_5d']>p['high']['return_5d'] or f['distance_ma20']>p['high']['distance_ma20'] or f['move_atr']>=config['atr']['extreme_multiple'] or (f.get('natr') is not None and f['natr']>=config['atr']['high_natr']):
        return '高位观察','累计延伸或ATR过热；高上涨概率不等于适合追涨'
    if f['return_5d']<0 and f['slope_ma20']>0 and abs(f['distance_ma20'])<=p['pullback']['max_abs_distance_ma20'] and ratio is not None and ratio<p['pullback']['max_amount_ratio']:
        return '回调观察','中期上行、靠近MA20、缩量回调；首次回踩待验证'
    if sector.get('state') in config['sector']['allowed'] and f['return_5d']<=p['startup']['max_return_5d'] and 0<=f['distance_ma20']<=p['startup']['max_distance_ma20'] and ratio is not None and ratio>=p['startup']['min_amount_ratio'] and f.get('breakout'):
        return '启动观察','板块扩散、放量突破、位置合理'
    if f.get('bull_alignment') and f['return_20d']>p['trend']['min_return_20d'] and 0<=f['distance_ma20']<=p['trend']['max_distance_ma20']:
        return '趋势观察','MA5>MA10>MA20，趋势与位置满足规则'
    return '排除','未达到启动、趋势或回调规则'
