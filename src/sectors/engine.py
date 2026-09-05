import statistics

def sector_scores(quotes, membership, factors, config):
    by_code = {q.code: q for q in quotes}
    result = []
    for sector in membership:
        members = [by_code[c] for c in sector['codes'] if c in by_code]
        if not members:
            continue
        fs = [factors[q.code] for q in members if q.code in factors]
        changes = [q.change_pct for q in members]
        breadth = sum(x > 0 for x in changes) / len(changes)
        median = statistics.median(changes)
        trend = [f['price'] > f['ma20'] for f in fs if f.get('ma20')]
        w = config['sector']['weights']
        # Optional missing components are not silently filled with a neutral score.
        score = (breadth*100*w['breadth'] + max(0,min(100,50+median*config['sector']['momentum_scale']))*w['momentum']) / (w['breadth']+w['momentum'])
        if trend and len(trend)/len(members)>=config['sector']['min_factor_coverage']:
            score = score*(w['breadth']+w['momentum']) + statistics.mean(trend)*100*w['trend']
        amounts = [q.amount for q in members]
        concentration = max(amounts)/sum(amounts) if sum(amounts)>0 else None
        r20 = [f['return_20d'] for f in fs if f.get('return_20d') is not None]
        high = bool(r20 and statistics.median(r20)>config['sector']['high_return_20d'])
        if score < config['sector']['weak_threshold']:
            state = '转弱/退潮'
        elif high or (concentration and concentration > config['sector']['concentration_warning'] and breadth < 0.5):
            state = '高位拥挤'
        elif score >= config['sector']['strong_threshold']:
            state = '持续强势'
        elif score >= config['sector']['strengthening_threshold']:
            state = '正在加强'
        else:
            state = '启动观察'
        item = {'id': sector['id'], 'name': sector['name'], 'kind': sector['kind'], 'score': round(score,2), 'state': state, 'member_count':len(members), 'up':sum(x>0 for x in changes), 'down':sum(x<0 for x in changes), 'breadth':breadth, 'return_1d':median, 'amount':sum(amounts), 'concentration':concentration, 'above_ma20_ratio': statistics.mean(trend) if trend else None, 'factor_coverage':len(fs)/len(members), 'history':{}, 'missing_factors':['龙头/先锋身份','连板梯队','真实资金拥挤度'], 'source':sector.get('source')}
        for n in [3,5,10,20]:
            vals=[f[f'return_{n}d'] for f in fs if f.get(f'return_{n}d') is not None]
            item[f'return_{n}d']=statistics.median(vals) if vals else None
        for key in ['consecutive_up_2','consecutive_up_3','new_high_5d','new_high_20d']:
            item[key]=sum(f.get(key,False) for f in fs) if fs else None
        for n in [5,10,20]:
            vals=[f.get(f'amount_mean_{n}d') for f in fs]
            item[f'amount_mean_{n}d']=sum(vals) if vals and all(v is not None for v in vals) and len(fs)==len(members) else None
        result.append(item)
    return sorted(result,key=lambda s:s['score'],reverse=True)
