from src.risk.position import classify
from src.catalysts.engine import independent

def clamp(x): return max(0,min(100,x))

def analyze_stocks(quotes,factors,sectors,membership,events,market,config,limit_pool=None):
    sectors_by_id={s['id']:s for s in sectors}
    links={}
    for s in membership:
        for code in s['codes']:
            if s['id'] in sectors_by_id:
                links.setdefault(code,[]).append(sectors_by_id[s['id']])
    limit_pool={r['code']:r for r in (limit_pool or [])}
    stocks=[]
    for q in quotes:
        f=factors.get(q.code,{})
        available=links.get(q.code,[])
        sector=max(available,key=lambda s:s['score']) if available else {'id':None,'name':'未映射板块','score':None,'state':None}
        ev=[e for e in events if e['stock_code']==q.code]
        hard=any(e['event_type'] in config['risk']['hard_event_types'] for e in ev)
        hard=hard or (config['risk']['exclude_st'] and ('ST' in q.name.upper() or '退' in q.name)) or q.amount<config['risk']['min_amount']
        independent_events=[e for e in ev if independent(e,config)]
        position,reason=classify(f,sector if not independent_events else {**sector,'state':None},config,hard)
        if sector['score'] is None and not independent_events:
            position,reason='排除','缺少可靠板块映射'
        if sector.get('state') not in config['sector']['allowed'] and not independent_events and position!='高位观察':
            position,reason='排除','板块未通过第二层筛选'
        atr=f.get('move_atr')
        atr_state='未知' if atr is None else '极端' if atr>=config['atr']['extreme_multiple'] else '警告' if atr>=config['atr']['warning_multiple'] else '正常'
        r=config['risk']
        penalty=(r['weak_market_penalty'] if market.get('environment')=='偏弱' else 0)+(r['high_position_penalty'] if position=='高位观察' else 0)+(r['atr_extreme_penalty'] if atr_state=='极端' else r['atr_warning_penalty'] if atr_state=='警告' else 0)
        components={'trend':None,'sector':sector['score'],'position':config['scoring']['position_scores'][position],'volume':None}
        if f.get('return_20d') is not None:
            components['trend']=clamp(config['scoring']['trend_base']+f['return_20d']*config['scoring']['trend_return_multiplier']+config['scoring']['trend_alignment_bonus']*f.get('bull_alignment',False))
        if f.get('amount_ratio_5d') is not None:
            components['volume']=clamp(config['scoring']['volume_base']+config['scoring']['volume_multiplier']*min(f['amount_ratio_5d'],2))
        weights=config['scoring']['weights']
        coverage=sum(weights[k] for k,v in components.items() if v is not None)
        score=clamp(sum(weights[k]*v for k,v in components.items() if v is not None)/coverage-penalty) if coverage else None
        limit=limit_pool.get(q.code,{})
        is_limit=q.limit_up_price is not None and abs(q.price-q.limit_up_price)<0.0051 or q.code in limit_pool
        volume_type='成交额历史缺失'
        if f.get('amount_ratio_5d') is not None:
            expanded=f['amount_ratio_5d']>=config['position']['startup']['min_amount_ratio']
            volume_type='放量突破' if expanded and f.get('breakout') else '放量滞涨' if expanded and q.change_pct<=0 else '放量' if expanded else '缩量上涨' if q.change_pct>0 else '缩量回调'
        stocks.append({**q.model_dump(mode='json'),**f,'stock_code':q.code,'stock_name':q.name,'sector':sector['name'],'sector_id':sector['id'],'sector_score':sector['score'],'sector_state':sector['state'],'market_score':market.get('score'),'position_type':position,'atr_state':atr_state,'atr_risk':penalty,'risk_score':penalty,'risk':'高' if hard or penalty>=r['high_threshold'] else '中' if penalty>=r['medium_threshold'] else '低','hard_risk':hard,'total_score':round(score,2) if score is not None else None,'score_coverage':round(coverage,2),'scores':components,'tradability_score':None,'tradability_basis':'NOT_ASSESSED','risk_scope':'TECHNICAL_AND_KNOWN_FLAGS','technical_risk':('高' if penalty>=r['high_threshold'] else '中' if penalty>=r['medium_threshold'] else '低'),'event_review_status':('UNREVIEWED' if not ev else 'SUPPORTED_FACTS_VERIFIED' if all(e.get('verified') for e in ev) else 'PARTIAL'),'score_status':'COMPLETE' if coverage>=.999 else 'PARTIAL','eligibility_notes':[('缺少'+{'trend':'趋势','sector':'板块','position':'位置','volume':'历史成交额'}[k]+'因子') for k,v in components.items() if v is None],'subjective_probability':None,'probability_basis':'未校准，不输出伪精确概率','deep_score':None,'deep_components':{k:None for k in config['scoring']['deep_weights']},'board_count':limit.get('board_count'),'derived_board_count':limit.get('derived_board_count'),'limit_identity_basis':limit.get('identity_basis'),'is_limit_up':bool(is_limit),'limit_details':limit,'volume_type':volume_type,'events':ev,'independent_catalyst':bool(independent_events),'catalyst_score':max((e['impact_score'] for e in independent_events),default=None),'expectation_score':None,'positive_factor':reason if position!='排除' else '无已确认优势','negative_factor':reason if position in ('排除','高位观察') else ('部分公告待人工复核，已核验事实见事件证据' if ev else '独立催化与龙虎榜尚未确认'),'validation_condition':f"板块维持扩散，价格守住MA20（{format(f['ma20'], '.2f') if f.get('ma20') is not None else '待补'}），ATR不过热",'invalidation_condition':'板块转弱、放量跌破MA20或出现重大风险公告','exclusion_reason':reason if position=='排除' else None,'rank_history':[]})
    return stocks
