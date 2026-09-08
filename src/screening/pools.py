from datetime import timedelta

def predecessor(day,stage,calendar):
    if stage=='0730': return (calendar.previous(day),'2130')
    mapping={'2130':(day,'1600'),'0830':(day,'0730'),'1135':(day,'0830')}
    return mapping.get(stage)

def pools(stocks,stage,config,previous=None):
    limits=config['candidate_pool']
    selected={'POOL_A':[],'POOL_B':[],'POOL_C':[]}
    previous_by_code={s['stock_code']:s for v in (previous or {}).get('pools',{}).values() for s in v}
    previous_codes=set(previous_by_code)
    for s in stocks:
        fresh_catalyst=stage in ('2130','0730','0830') and s['independent_catalyst']
        if stage!='1600' and s['stock_code'] not in previous_codes and not fresh_catalyst:
            continue
        if s['position_type']=='排除' or (s['total_score'] or 0)<limits['min_score']:
            continue
        if fresh_catalyst and previous_by_code.get(s['stock_code'],{}).get('pool')!='POOL_A':
            pool='POOL_C'
        elif stage!='1600':
            pool=previous_by_code[s['stock_code']]['pool']
        elif s['is_limit_up']:
            pool='POOL_A'
        elif s['independent_catalyst']:
            pool='POOL_C'
        elif s['position_type'] in ('启动观察','趋势观察','回调观察'):
            pool='POOL_B'
        else:
            continue
        s={**s,'pool':pool}
        old=previous_by_code.get(s['stock_code'])
        if old:
            delta=(s['total_score'] or 0)-(old['total_score'] or 0)
            s['transition']='上调' if delta>0 else '下调' if delta<0 else '维持'
        else:
            s['transition']='新入池'
        selected[pool].append(s)
    cap={'POOL_A':limits['evening_limit_max'] if stage=='2130' else limits['limit_pool_max'],'POOL_B':limits['trend_pool_max'],'POOL_C':limits['catalyst_pool_max']}
    for pool in selected:
        selected[pool]=sorted(selected[pool],key=lambda s:(-(s['total_score'] or 0),s['stock_code']))[:cap[pool]]
    total_cap={'0730':limits['overnight_max'],'0830':limits['premarket_max'],'1135':limits['midday_max']}.get(stage)
    if total_cap:
        best=sorted([s for group in selected.values() for s in group],key=lambda s:-(s['total_score'] or 0))[:total_cap]
        codes={s['stock_code'] for s in best}
        selected={pool:[s for s in group if s['stock_code'] in codes] for pool,group in selected.items()}
    for pool,group in selected.items():
        for i,s in enumerate(group,1): s['rank']=i
    survivors={s['stock_code'] for g in selected.values() for s in g}
    changes=[{'stock_code':code,'transition':'淘汰','reason':next((s.get('exclusion_reason') or '排名未进入阶段上限' for s in stocks if s['stock_code']==code),'缺少可靠更新数据')} for code in previous_codes-survivors]
    return selected,changes

def midday_validate(stocks,previous,market,config):
    original={s['stock_code']:s for g in previous['pools'].values() for s in g}
    result=[]
    threshold=config['validation']
    for s in stocks:
        if s['stock_code'] not in original: continue
        base=original[s['stock_code']]
        ret=(s['price']/base['price']-1)*100
        label='D 证伪' if s['position_type']=='排除' or ret<=threshold['invalid_return'] else 'S 强确认' if ret>=threshold['strong_return'] and s['atr_state']=='正常' else 'A 确认' if ret>=threshold['confirmed_return'] else 'C 低于预期' if ret<=threshold['weak_return'] else 'B 观察'
        s.update(validation_label=label,morning_return=ret,morning_open=s['open'],afternoon_condition=s['validation_condition'])
        result.append(s)
    return result
