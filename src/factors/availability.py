"""Data availability is separate from model capability and operational health."""

def factor_statuses(run):
    market=run.get('market',{})
    context=run.get('market_context') or market.get('context') or {}
    limits=run.get('limit_pool',[])
    candidates=[s for rows in run.get('pools',{}).values() for s in rows]
    sectors=run.get('sectors',[])
    wudao=run.get('wudao') or {}
    funds=[r for name in ('featured','industry') for r in (wudao.get(name) or {}).get('rows',[]) if r.get('mainNetAmount') is not None]
    result=[]
    def add(key,label,status,reason,coverage=None,source=None,used=False):
        result.append(dict(id=key,label=label,status=status,reason=reason,coverage=coverage,
                           source=source,as_of_time=run.get('as_of_time'),used_in_score=used))
    add('breadth','市场广度','AVAILABLE' if market.get('score') is not None else 'UNAVAILABLE',
        '市场分仅使用上涨占比和涨跌幅中位数',run.get('data_quality',{}).get('coverage'),'全市场行情',market.get('score') is not None)
    add('ladder','首板与连板梯队','AVAILABLE' if limits else 'UNAVAILABLE',
        f'已知涨停记录{len(limits)}条；供应商口径与规则推导分开，未纳入广度评分' if limits else '缺少有效涨停名单，不能按0家解释',source='涨停证据')
    boards=[r['board_count'] for r in limits if type(r.get('board_count')) is int]
    add('highest_board','供应商最高板','AVAILABLE' if boards else 'UNAVAILABLE',
        f'供应商记录最高{max(boards)}板；不等于全市场梯队完整性已核验' if boards else '没有有效供应商板数',source='涨停证据')
    limit_coverage=min(market.get('limit_up_price_coverage',0),market.get('limit_down_price_coverage',0))
    add('limit_coverage','全市场涨跌停价覆盖','AVAILABLE' if limit_coverage>=1 else 'PARTIAL' if limit_coverage>0 else 'UNAVAILABLE',
        '独立涨停名单与全市场每只股票的上下限价格是不同覆盖口径',min(market.get('limit_up_price_coverage',0),market.get('limit_down_price_coverage',0)))
    amount_ready=sum(s.get('amount_ratio_5d') is not None for s in candidates)
    add('stock_amount','候选历史成交额','AVAILABLE' if candidates and amount_ready==len(candidates) else 'PARTIAL' if amount_ready else 'UNAVAILABLE',
        f'{amount_ready}/{len(candidates)}只候选具备成交额基线；缺失时启动/回调条件无法完整验证',amount_ready/len(candidates) if candidates else None,'历史日线',True)
    # Market context owns its definitions and per-source status. Preserve its evidence.
    context_statuses=context.get('factor_statuses',[])
    for item in context_statuses:
        if isinstance(item,dict) and item.get('id'):
            result.append({**item,'as_of_time':item.get('as_of_time',run.get('as_of_time'))})
    names={item['id'] for item in result}
    for key,label,reason in [
        ('break_rate','炸板率','需要完整触板未封住名单及同口径涨停名单'),
        ('yesterday_premium','昨日涨停溢价','需要前一交易日涨停集合及本日匹配行情'),
        ('promotion','连板晋级率','需要跨交易日相同股票的板数迁移'),
        ('market_amount','市场成交额5/10/20日基线','需要连续交易日、同口径全市场总成交额'),
        ('index_trend','指数5/10/20日趋势','需要有效指数日线'),
        ('high_board_loss','高位股亏钱效应','需要前一交易日高板群组及匹配行情')]:
        if key not in names: add(key,label,'UNAVAILABLE',reason)
    add('sentiment_cycle','短线情绪周期','NOT_INTEGRATED','周期模型尚未校准；广度分不代表完整短线情绪')
    add('main_flow','板块主力净额','AVAILABLE' if funds else 'UNAVAILABLE',
        f'{len(funds)}条板块供应商资金记录可用，非全市场资金归因，未纳入广度评分',source='悟道')
    add('external','外部市场','NOT_INTEGRATED','隔夜外部变量尚未纳入；08:00市场分仍为前收盘参考')
    add('dragon_tiger','龙虎榜席位归因','NOT_INTEGRATED','席位记录不能直接证明买卖动机，归因未实现')
    events=run.get('events',[]); verified=sum(bool(e.get('verified')) for e in events)
    add('announcements','公告正文核验','MANUAL',f'{verified}/{len(events)}条事件通过支持范围内事实核验；其余类型与歧义仍待复核',verified/len(events) if events else None,'巨潮/公告原文')
    add('corporate_actions','历史复权事件校验','PARTIAL','现有未复权序列会隔离异常跳变；尚无完整公司行动校验')
    covered=sum(s.get('factor_member_count',round(s.get('factor_coverage',0)*s.get('member_count',0))) for s in sectors)
    total=sum(s.get('member_count',0) for s in sectors)
    add('sector_history','板块成分多日因子','AVAILABLE' if total and covered==total else 'PARTIAL',
        f'{covered}/{total}个板块成分席位有历史因子；跨板块股票可能重复',covered/total if total else None,'历史日线',True)
    add('causality','消息发布前后因果验证','NOT_INTEGRATED','新鲜度和累计涨幅仅是反应代理，尚不能验证因果')
    return result
