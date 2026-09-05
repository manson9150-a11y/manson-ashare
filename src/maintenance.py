"""Version sector metadata before a run, independently of quote freshness."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta
from pathlib import Path
import argparse,json,re
import yaml
from src.collectors.public import SinaAdapter
from src.utils.calendar import TZ,TradingCalendar
from src.utils.io import read_json,write_json

def refresh_membership(project,output=None,force=False):
    project=Path(project);output=Path(output or project);config=yaml.safe_load((project/'config/settings.yaml').read_text())
    target=output/'data/latest/membership.json';old=read_json(target,{})
    now=datetime.now(TZ)
    if old.get('observed_at') and not force and now-datetime.fromisoformat(old['observed_at'])<timedelta(days=1):return old
    adapter=SinaAdapter(config)
    response=adapter.get('https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php')
    raw=response.content.decode('gb18030')
    # Parse JSON data, never evaluate third-party JavaScript.
    payload=json.loads(raw[raw.index('{'):raw.rindex('}')+1])
    catalog=[(key,value.split(',')[1]) for key,value in payload.items()]
    def members(item):
        key,name=item;codes=[]
        for page in range(1,30):
            batch=adapter.get('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData',params={'page':page,'num':100,'sort':'symbol','asc':1,'node':key,'symbol':''}).json()
            if not batch:break
            codes.extend(r['code'] for r in batch if re.fullmatch(r'\d{6}',r.get('code','')))
            if len(batch)<100:break
        return {'id':'sina:'+key,'name':name,'kind':'industry','codes':sorted(set(codes)),'source':'sina_industry_metadata'}
    rows=[];failed=[]
    with ThreadPoolExecutor(max_workers=config['sources']['workers']) as ex:
        jobs={ex.submit(members,item):item[0] for item in catalog}
        for future in as_completed(jobs):
            try:
                row=future.result()
                if row['codes']:rows.append(row)
            except Exception as exc:failed.append({'id':jobs[future],'error':type(exc).__name__})
    result={'observed_at':datetime.now(TZ).isoformat(),'source':'https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php','scope':'行业分类元数据；不使用该页面的无日期行情','sectors':sorted(rows,key=lambda x:x['id']),'failed':failed}
    if rows:write_json(target,result)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--force',action='store_true');p.add_argument('--output',type=Path);args=p.parse_args()
    project=Path(__file__).resolve().parents[1]
    try:
        result=refresh_membership(project,args.output,args.force)
        print(json.dumps({'sectors':len(result['sectors']),'observed_at':result['observed_at'],'failed':len(result['failed'])}))
    except Exception as exc:
        print(json.dumps({'status':'METADATA_UNAVAILABLE','error':type(exc).__name__}))
if __name__=='__main__':main()
