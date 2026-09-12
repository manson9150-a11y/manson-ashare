"""Stock-first discovery and conditional research plans, never order signals.

All price levels use the frozen snapshot. Unadjusted prices and incomplete
announcement review remain explicit. High-volatility names get no entry zone.
"""
from datetime import datetime
from math import isfinite

VERSION = 'stock_focus_v1'
LABELS = {'POOL_B': '短期强势', 'POOL_C': '独立催化', 'POOL_H': '高波动观察'}


def tracking_seed(previous, seed, as_of):
    """An explicitly dated post-hoc list may seed a later prospective run."""
    if not seed or seed.get('base_run_id')!=previous.get('run_id') or seed.get('quote_date')!=previous.get('quote_date'):
        return previous
    try:
        generated=datetime.fromisoformat(seed['generated_at'])
        if generated.tzinfo is None or not datetime.fromisoformat(previous['as_of_time'])<generated<as_of: return previous
        if not seed.get('quotes') or not seed.get('factors') or not seed.get('pools'): return previous
        for q in seed['quotes']:
            if q['timestamp'][:10]!=seed['quote_date'] or datetime.fromisoformat(q['timestamp'])>generated: return previous
    except (KeyError,TypeError,ValueError): return previous
    return {**previous, 'pools':seed['pools'],'quotes':seed['quotes'],'factors':seed['factors'],
            'stock_research':seed['stock_research'],
            'research_seed_origin':{'base_run_id':seed['base_run_id'],'generated_at':seed['generated_at'],'kind':'POST_HOC_RESEARCH'}}


def enabled(config, stage):
    return config.get('stock_research', {}).get('enabled', False) and stage in ('0800', '1200', '2200')


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def history_candidates(quotes, independent_codes, good_codes, config, tracked=()):
    """Round-robin discovery reserves slots outside sector membership."""
    eligible = [q for q in quotes if not q.suspended and q.amount >= config['risk']['min_amount']
                and 'ST' not in q.name.upper() and '退' not in q.name]
    positive = [q for q in eligible if q.change_pct > 0]
    buckets = [
        sorted([q for q in positive if q.change_pct >= 2], key=lambda q: (-q.change_pct, -q.amount, q.code))[:100],
        sorted(positive, key=lambda q: (-q.amount, q.code))[:100],
        sorted([q for q in positive if number(q.turnover)], key=lambda q: (-q.turnover, -q.amount, q.code))[:60],
        sorted([q for q in eligible if q.code in good_codes], key=lambda q: (-q.amount, q.code)),
    ]
    result = sorted([q for q in eligible if q.code in independent_codes], key=lambda q: (-q.amount, q.code))[:20]
    result += sorted([q for q in eligible if q.code in set(tracked)], key=lambda q: (-q.amount, q.code))[:30]
    seen = set(); chosen = []
    def add(q):
        if q.code not in seen:
            seen.add(q.code); chosen.append(q)
    for q in result: add(q)
    for i in range(max((len(b) for b in buckets), default=0)):
        for b in buckets:
            if i < len(b): add(b[i])
    return chosen[:config['sources']['max_history_stocks']]


def select(stocks, stage, config, previous=None):
    """A is retired; H is explicitly observation-only, separate from B/C."""
    old = {s['stock_code']: s for g in (previous or {}).get('pools', {}).values() for s in g}
    selected = {'POOL_A': [], 'POOL_B': [], 'POOL_C': [], 'POOL_H': []}
    c = config['stock_research']
    for s in stocks:
        if s.get('hard_risk') or s.get('suspended') or not all(number(s.get(k)) for k in ('return_5d', 'return_20d', 'ma20', 'atr')):
            continue
        if stage != '2200' and s['stock_code'] not in old and not s.get('independent_catalyst'):
            continue
        hot = s['return_5d'] >= c['hot_return_5d'] or s['return_20d'] >= c['hot_return_20d'] or (s.get('natr') or 0) >= c['hot_natr']
        if hot and s['price'] > s['ma20'] and s['return_5d'] > 0:
            pool = 'POOL_H'
        elif s.get('position_type') == '排除':
            continue
        elif s.get('independent_catalyst'):
            pool = 'POOL_C'
        elif s['return_5d'] > 0 and s['return_20d'] > 0 and s['price'] > s['ma20'] and s.get('position_type') != '高位观察':
            pool = 'POOL_B'
        else:
            continue
        # Individual momentum ranks discovery; it is not a return probability.
        priority = s['return_5d'] + min(s['return_20d'], 40) * .2
        item = {**s, 'pool': pool, 'research_priority': round(priority, 2),
                'observation_only': pool == 'POOL_H',
                'transition': '继续跟踪' if s['stock_code'] in old else '首次纳入'}
        selected[pool].append(item)
    caps = {'POOL_A': 0, 'POOL_B': c['momentum_max'], 'POOL_C': c['catalyst_max'], 'POOL_H': c['volatile_max']}
    for pool, group in selected.items():
        selected[pool] = sorted(group, key=lambda s: (-s['research_priority'], s['stock_code']))[:caps[pool]]
        for rank, s in enumerate(selected[pool], 1): s['rank'] = rank
    survivors = {s['stock_code'] for g in selected.values() for s in g}
    by_code = {s['stock_code']: s for s in stocks}
    changes = []
    for code in sorted(set(old) - survivors):
        s = by_code.get(code)
        reason = '行情或历史因子未取得，暂停判断' if not s else s.get('exclusion_reason') or '短期强度条件或本阶段跟踪上限未满足'
        changes.append({'stock_code': code, 'stock_name': old[code]['stock_name'], 'transition': '暂停跟踪', 'reason': reason})
    return selected, changes


def catalyst_analysis(events):
    """Interpret supported facts; parser failures never prove a business fact."""
    if not events:
        return {'status': 'UNCONFIRMED', 'headline': '上涨依据目前来自价格，独立催化未确认',
                'conclusion': '现有材料不足以把股价强势归因于某项公司事件。先观察量价延续，不给消息驱动加分。',
                'next_check': '补充公司正式披露、事件发生时间与可量化经营影响。', 'source_event_ids': []}
    reviewed = sorted([e for e in events if (e.get('verification') or {}).get('analysis')], key=lambda e:e.get('publish_time',''), reverse=True)
    adverse = [e for e in reviewed if e['verification'].get('business_direction') in ('NEGATIVE_REVISION','CANCELLED')]
    if adverse:
        e=adverse[0]
        return {'status':'RISK','headline':'合同变更带来经营风险，先审查预期下修', 'conclusion':e['verification']['analysis'],
                'next_check':'核对同一项目的新旧金额与已执行部分；不要把存量合同变更算成新增订单。','source_event_ids':[e['event_id']]}
    verified = [e for e in events if e.get('verified') and (e.get('verification') or {}).get('status') == 'VERIFIED_RULE']
    if not verified:
        if reviewed:
            e=reviewed[0]
            return {'status':'UNCONFIRMED','headline':'经营线索值得跟踪，强催化条件尚未满足', 'conclusion':e['verification']['analysis'],
                    'next_check':'跟踪正式承诺、业务规模与履约回款；连续进展按同一事件核对，不累加公告金额。', 'source_event_ids':[e['event_id']]}
        if all(any(word in e.get('title','') for word in ('说明会','交流会','董事会','监事会','管理制度','治理','现金管理','章程')) for e in events):
            return {'status':'ROUTINE','headline':'例行披露，未形成新增经营催化',
                    'conclusion':'当前材料主要是投资者交流或公司治理安排，未提供新增订单、盈利增量等经营事实，不能据此解释股价上涨。',
                    'next_check':'关注后续是否披露可量化的经营变化；例行公告不重复增加催化权重。','source_event_ids':[e['event_id'] for e in events]}
        if not any('合同' in e.get('title','') or '订单' in e.get('title','') for e in events):
            return {'status':'UNCONFIRMED','headline':'公司事件尚无可量化增量证据',
                    'conclusion':'当前材料未确认对经营或利润的新增影响。将其保留为待查背景，不能靠公告数量为价格上涨提供理由。',
                    'next_check':'核对事件实质、与历史预期的差别及可兑现的经营变化；业绩事项还需区分说明会安排与实际业绩预告。',
                    'source_event_ids':[e['event_id'] for e in events]}
        return {'status': 'UNCONFIRMED', 'headline': '线索尚不能构成已证实的独立催化',
                'conclusion': '已有公告线索，但保存的结构化证据未证明新增经营收益及兑现条件。核验程序未通过也不等于公告没有价值；不能据标题判断利好。',
                'next_check': '核对合同新增还是变更、净增金额、营收占比、履约期限和利润兑现条件。',
                'source_event_ids': [e['event_id'] for e in events]}
    e = max(verified, key=lambda e: e.get('publish_time', ''))
    v = e['verification']; facts = v.get('facts', {})
    if v.get('materiality_pct') is not None:
        fact_text=f"已签合同金额约占所披露完整年度营收的{v['materiality_pct']:.2f}%"
    elif v.get('contract_amount_yuan') is not None:
        fact_text=f"已签署生效的销售合同总额约{v['contract_amount_yuan']/1e8:.2f}亿元，履约期限：{v.get('contract_duration','待核对')}"
    elif v.get('rule')=='POSITIVE_PROFIT_FORECAST_GROWTH_50PCT':
        return {'status':'FACTS_VERIFIED','headline':'正向业绩预告有依据，关注增长质量与兑现',
                'conclusion':'已核验公司预计归母净利润为正，且同比增长区间下限至少50%。需区分低基数、非经常性损益和主营增长；业绩预告不等于最终已实现业绩。',
                'next_check':'对照定期报告确认实际净利润、扣非表现与现金流，避免只按同比增速推算股价空间。','source_event_ids':[e['event_id']]}
    else: fact_text='当前事件已有支持的量化事实'
    return {'status': 'FACTS_VERIFIED', 'headline': '经营事实有证据，短期股价反应仍需验证',
            'conclusion': f'{fact_text}。这支持继续研究公司事件，但合同金额不等于本期收入或利润，不能据此推导目标价。',
            'next_check': '确认收入确认周期、回款与成本约束；对照事件前后涨幅，避免把已发生的上涨当成未来收益。',
            'facts': facts, 'source_event_ids': [e['event_id']]}


def price_plan(s, run, config):
    result = {'status': 'WAIT_DATA', 'label': '暂不形成入场区间', 'entry_zone': None,
              'invalidation_price': None, 'resistance_reference': None, 'reward_risk_to_resistance': None,
              'quote_time': s.get('timestamp'), 'quote_date': run.get('quote_date'),
              'basis': '未复权日线 MA10 与 ATR14 的条件研究；不是实时委托价。',
              'trigger': '等待有效历史价格与成交额证据。',
              'no_trade': ['出现重大风险公告或除权除息，重新计算价格条件。', '跳空、停牌或涨停无法成交时，不按参考价格假定可以买入。'],
              'valid_until': '下一份正式阶段报告；若实际价格或公司行动已变化，旧区间停止使用。'}
    if s.get('pool') == 'POOL_H' or s.get('observation_only'):
        result.update(status='OBSERVE_ONLY', label='高波动，只跟踪不追价', trigger='等待波动收敛、可验证的承接和新的正式研究；不根据“妖股”标签生成买点。')
        return result
    if s.get('hard_risk') or s.get('position_type') == '排除':
        result.update(status='INVALIDATED', label='当前条件不支持入场', trigger='先排除已识别风险或趋势破坏。')
        return result
    required = ('price', 'ma10', 'ma20', 'atr', 'return_5d')
    if not all(number(s.get(k)) and (s[k] > 0 if k != 'return_5d' else True) for k in required): return result
    try:
        quote_time=datetime.fromisoformat(s['timestamp'])
        cutoff=datetime.fromisoformat(run['as_of_time'])
        if quote_time.tzinfo is None or cutoff.tzinfo is None or quote_time>cutoff or s['timestamp'][:10]!=run['quote_date'] or s.get('bars_count',0)<61: return result
    except (KeyError,TypeError,ValueError): return result
    if s['price'] < s['ma20']:
        result.update(status='INVALIDATED', label='趋势条件已失效', trigger='价格低于 MA20，等待新的结构。'); return result
    if run.get('stage') in ('1200', '1135') and s.get('amount_ratio_5d') is None:
        result.update(status='WAIT_CONFIRMATION', label='午间量能待确认', trigger='没有同时间成交额基线，保留观察；晚间完整日线后重算区间。'); return result
    if not number(s.get('amount_ratio_5d')):
        result['trigger'] = '成交额历史缺失，暂不发布价格计划。'; return result
    ma, atr = s['ma10'], s['atr']
    low = round(ma - .2 * atr, 2); high = round(ma + .2 * atr, 2)
    stop = round(min(ma - .8 * atr, low - .01), 2)
    if stop <= 0 or not stop < low < high: return result
    result.update(status='WAIT_PULLBACK', label='等待回踩确认', entry_zone=[low, high], invalidation_price=stop,
                  trigger=f'回踩 {low:.2f}–{high:.2f} 后重新站稳 MA10，且卖压收敛；触及区间本身不构成买入确认。')
    if s['price'] > high + atr:
        result.update(status='NO_CHASE', label='距离观察区较远，不追价')
    if s.get('is_limit_up'):
        result.update(status='WAIT_LIQUIDITY', label='涨停状态，等待可成交与承接验证')
    bars = s.get('bars', [])
    highs = [b['high'] for b in bars[-20:] if number(b.get('high'))]
    resistance = max(highs) if len(highs) >= 20 else None
    if resistance and resistance > high:
        ratio = (resistance-high)/(high-stop)
        result.update(resistance_reference=round(resistance, 2), reward_risk_to_resistance=round(ratio, 2))
        if ratio < config.get('stock_research', {}).get('min_reward_risk', 1.5):
            result.update(status='WAIT_SPACE', label='至前高空间不足，继续等待')
    result['no_trade'].append(f'跌破 {stop:.2f} 或出现放量破位时，本条件失效；跳空可能越过该价。')
    return result


def attach(run, config, previous=None, generated_at=None):
    previous_by_code = {s['stock_code']: s for g in (previous or {}).get('pools', {}).values() for s in g}
    for pool, group in run.get('pools', {}).items():
        if pool not in LABELS: continue
        for s in group:
            pieces = []
            if number(s.get('return_5d')): pieces.append(f"近5日{s['return_5d']:+.1f}%")
            if number(s.get('return_20d')): pieces.append(f"近20日{s['return_20d']:+.1f}%")
            if number(s.get('distance_ma20')): pieces.append(f"距MA20 {s['distance_ma20']:+.1f}%")
            vol = s.get('amount_ratio_5d')
            volume = f'当日成交额为前5日均值的{vol:.2f}倍' if number(vol) else '尚无可比成交额倍数'
            if pool == 'POOL_H':
                headline = '短期涨速或波动显著，先观察承接'
                conclusion = '、'.join(pieces) + f'；{volume}。价格弹性高，同时更容易发生急跌和流动性变化；不能据此断言会成为妖股。'
            else:
                headline = '趋势仍在，量能尚未跟上' if number(vol) and vol<1 else '放量走强，等待合理入场位置' if number(vol) and vol>=2 else '趋势延续，等待回踩确认'
                conclusion = '、'.join(pieces) + f'；{volume}。' + ('量能尚未高于近期均值，延续强势仍需新增承接。' if number(vol) and vol < 1 else '有成交参与，但仍需价格结构确认，放量本身不能证明资金意图。')
            catalyst = catalyst_analysis(s.get('events', []))
            old = previous_by_code.get(s['stock_code'])
            change = {'label': '首次纳入本版跟踪', 'previous_run_id': None, 'price_change_pct': None, 'previous_plan_status': None}
            if old and number(old.get('price')) and old['price'] > 0:
                delta = (s['price']/old['price']-1)*100
                old_plan = old.get('research', {}).get('price_plan', {})
                old_stop = old_plan.get('invalidation_price')
                broken = number(old_stop) and s['price'] < old_stop
                change = {'label': '前次条件已失效' if broken else '继续跟踪', 'previous_run_id': previous.get('run_id'),
                          'previous_time': previous.get('as_of_time'), 'price_change_pct': round(delta, 2), 'previous_plan_status': old_plan.get('status')}
            plan=price_plan(s,run,config)
            if change['label']=='前次条件已失效':
                plan.update(status='INVALIDATED',label='前次条件失效，暂停新入场计划',entry_zone=None,invalidation_price=None,
                            trigger='当前快照已低于前次失效参考。先复核原判断，不能通过降低失效线继续维持买点。')
            s['research'] = {'version': VERSION, 'category': LABELS[pool], 'headline': headline, 'conclusion': conclusion,
                             'catalyst': catalyst, 'price_plan': plan, 'change': change,
                             'basis': 'EVIDENCE_RULES', 'limitations': ['公司行动尚未完整核验，未复权技术位置须复核。', '公告扫描有范围和篇数限制，未发现不等于不存在风险。']}
    run['stock_research'] = {'version': VERSION, 'generated_at': generated_at or run.get('as_of_time'),
                             'quote_date': run.get('quote_date'), 'analysis_basis': 'EVIDENCE_RULES',
                             'coverage': run.get('funnel', {}), 'labels': LABELS,
                             'note': '系统依据明确量价规则和已核验事实生成研究结论；未启用语言模型深度研判。高波动观察不是买入名单。'}
    reviewed={}
    names={q.get('code',q.get('stock_code')):q.get('name',q.get('stock_name')) for q in run.get('quotes',[])}
    for e in run.get('events',[]):
        if e.get('verification'): reviewed.setdefault(e['stock_code'],[]).append(e)
    run['stock_research']['catalyst_reviews']=[{'stock_code':code,'stock_name':names.get(code,code),
        **catalyst_analysis(events),'sources':[{'url':e.get('document_url') or e['url'],'title':e['title'],'published_at':e['publish_time']} for e in events]}
        for code,events in reviewed.items()]
    return run
