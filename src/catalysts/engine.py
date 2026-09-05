import hashlib
import re
from datetime import datetime
from src.models import Event

def deduplicate(events, as_of):
    result={}
    for e in events:
        if e.publish_time>as_of or e.event_time>as_of:
            continue
        # Prefer official document/canonical ids; title fallback handles exact syndication.
        normalized=re.sub(r'[\W_]+','',e.title).lower()
        key=e.canonical_id or f'{e.stock_code}:{e.event_type}:{e.event_time.date()}:{normalized}'
        if key not in result or (e.reliability,e.publish_time)>(result[key].reliability,result[key].publish_time):
            result[key]=e
    return list(result.values())

def expectation(events, factors, as_of, config):
    result=[]
    c=config['catalyst']
    for e in deduplicate(events,as_of):
        age=max(0,(as_of-e.publish_time).total_seconds()/3600)
        freshness=max(0,1-age/c['freshness_hours'])
        f=factors.get(e.stock_code,{})
        r=f.get('return_20d')
        label=None if r is None else 'Overpriced' if r>=c['overpriced_return'] else 'Mostly Priced' if r>=c['mostly_priced_return'] else 'Partially Priced' if r>=c['partly_priced_return'] else 'Fresh Catalyst'
        d=e.model_dump(mode='json')
        d.update(freshness=freshness, expectation=label, priced_in_score=None if r is None else max(0,min(100,r/c['overpriced_return']*100)), expectation_basis='规则代理：新鲜度与20日涨幅；未证明因果关系')
        result.append(d)
    return result

def independent(event, config):
    c=config['catalyst']
    return event['verified'] and event['reliability']>=c['independent_min_reliability'] and event['directness']>=c['independent_min_directness'] and (event['impact_score'] or 0)>=c['independent_min_impact'] and event['freshness']>0 and event['event_type'] not in config['risk']['hard_event_types']
