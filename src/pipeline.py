from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from collections import Counter
from pathlib import Path
import uuid
import copy
import pandas as pd
import yaml
from src.models import Quote, Event
from src.utils.calendar import TradingCalendar, CalendarUnknown, TZ, stage_time
from src.utils.io import read_json, write_json, clean
from src.collectors.base import Collector, Unavailable
from src.collectors.public import EastmoneyAdapter, TencentAdapter, SinaAdapter
from src.collectors.announcements import AnnouncementAdapter
from src.normalizers.quality import validate_quotes, validate_bars
from src.factors.technical import technical
from src.market.engine import market_score
from src.sectors.engine import sector_scores
from src.stocks.engine import analyze_stocks
from src.catalysts.engine import expectation
from src.screening.pools import predecessor, pools, midday_validate
from src.reports.render import stage_markdown, daily_markdown
from src.google_docs.writer import DocsOutbox
from src.ai.analyst import enhance
from src.evaluation.engine import update_outcomes

class Pipeline:
    def __init__(self, project, output=None, mode='live', config=None):
        self.project=Path(project).resolve(); self.output=Path(output or project).resolve(); self.mode=mode
        self.config=config or yaml.safe_load((self.project/'config/settings.yaml').read_text())
        self.calendar=TradingCalendar(self.project/'config/calendar.json')
        self.collector=Collector([c(self.config) for c in [EastmoneyAdapter,TencentAdapter,SinaAdapter] if c.source_name in self.config['sources']['enabled']])
        self.announcements=Collector([AnnouncementAdapter(self.config)])
    def stage_path(self, day, stage):
        return self.output/'data/history'/day.strftime('%Y/%m/%d')/stage/'stage_results.json'
    def status_only(self, run, status, message):
        run.update(status=status,warnings=[message],finished_at=datetime.now(TZ).isoformat())
        write_json(self.output/'data/latest/run_status.json',run)
        write_json(self.output/'reports/runs'/f"{run['run_id']}.json",run)
        return run
    def run(self, day, stage, now=None):
        now=now or datetime.now(TZ)
        if now.tzinfo is None: raise ValueError('timezone required')
        now=now.astimezone(TZ); as_of=stage_time(day,stage,self.config)
        run={'run_id':uuid.uuid4().hex,'date':str(day),'stage':stage,'stage_label':self.config['stages'][stage]['label'],'mode':self.mode,'started_at':now.isoformat(),'as_of_time':as_of.isoformat(),'status':'RUNNING','warnings':[],'errors':[],'data_quality':{'status':'RED'},'pools':{'POOL_A':[],'POOL_B':[],'POOL_C':[]},'sectors':[],'market':{},'eliminations':[],'missing_factors':[]}
        try: trading=self.calendar.is_trading_day(day)
        except CalendarUnknown as e: return self.status_only(run,'CALENDAR_UNVERIFIED',str(e))
        if not trading: return self.status_only(run,'NON_TRADING_DAY','休市；未采集或生成伪行情报告')
        if self.mode=='live':
            deadline=datetime.fromisoformat(f"{day}T{self.config['stages'][stage]['deadline']}:00").replace(tzinfo=TZ)
            if now.date()!=day or now<as_of or now>deadline:
                return self.status_only(run,'OUTSIDE_STAGE_WINDOW','超出阶段时间窗。历史阶段只可读取已保存快照，不能用当前接口倒填。')
        run['scheduled_for']=as_of.isoformat()
        if self.mode=='live':
            run['schedule_delay_seconds']=(now-as_of).total_seconds()
            as_of=now
            run['as_of_time']=as_of.isoformat()
        existing=read_json(self.stage_path(day,stage))
        if existing and existing.get('status')=='COMPLETE':
            existing['google_docs']=DocsOutbox(self.output).flush() if self.mode=='live' else {'status':'DEMO_DISABLED'}
            return existing
        previous=None; key=predecessor(day,stage,self.calendar)
        if key:
            previous=read_json(self.stage_path(*key))
            initialization = None
            if previous is None and self.mode == 'live' and stage == '0730':
                from src.bootstrap import load_seed
                initialization = load_seed(self.output, day, as_of, self.calendar, self.config)
                if initialization:
                    previous = initialization
            if not initialization and (not previous or previous.get('status')!='COMPLETE' or previous.get('data_quality',{}).get('status')=='RED' or datetime.fromisoformat(previous['as_of_time'])>=as_of or previous.get('mode')!=self.mode):
                run['status']='MISSING_PREDECESSOR'; run['warnings'].append(f'缺少有效正式前序：{key[0]} {key[1]}；不重新海选。')
                return self.finish(run)
            run['predecessor']={'date':previous['date'],'stage':'BOOTSTRAP' if initialization else key[1],'run_id':previous['run_id']}
            if previous.get('bootstrap_origin'):
                run['bootstrap_origin'] = copy.deepcopy(previous['bootstrap_origin'])
                run['warnings'].append('首次启动链：承接周末初始化快照；使用事后行业分类，历史公告风险未完整核验。本轮不计入常规因子效果统计。')
        try: self.compute(run,day,stage,as_of,previous)
        except Exception as exc:
            run['status']='DEGRADED'; run['data_quality']['status']='RED'; run['errors'].append({'module':'pipeline','error':type(exc).__name__})
            run['warnings'].append('关键数据采集或计算失败；保留已有结果，不输出正式候选。')
            run['pools']={k:[] for k in run['pools']}
        return self.finish(run)
    def membership(self, quotes, as_of):
        groups={}
        for q in quotes:
            if q.industry: groups.setdefault(q.industry,[]).append(q.code)
        result=[{'id':'industry:'+name,'name':name,'kind':'industry','codes':codes,'source':'eastmoney'} for name,codes in groups.items()]
        metadata=read_json(self.output/'data/latest/membership.json',{})
        if not result and metadata.get('observed_at') and datetime.fromisoformat(metadata['observed_at'])<=as_of:
            age=(as_of-datetime.fromisoformat(metadata['observed_at'])).total_seconds()/86400
            if age<=self.config['sources']['membership_max_age_days']:
                result=metadata.get('sectors',[])
        try:
            sectors=self.collector.fetch('sectors')
            valid=[s for s in sectors if s.get('timestamp') and datetime.fromisoformat(s['timestamp'])<=as_of and s['timestamp'][:10]==str(as_of.date())]
            chosen=sorted(valid,key=lambda s:-(s['change_pct'] or -999))
            if result: chosen=[s for s in chosen if s['kind']=='concept']
            for s in chosen[:self.config['sources']['sector_membership_limit']]:
                try: result.append({**s,'codes':self.collector.fetch('members',sector_id=s['id'])})
                except Unavailable: continue
        except Unavailable: pass
        return result
    def compute(self, run, day, stage, as_of, previous):
        demo=None
        if self.mode=='demo':
            from src.collectors.demo import DemoData
            demo=DemoData(self.calendar,as_of,stage)
            run['warnings'].append('DEMO / 模拟数据：所有企业、事件和评分仅用于流程测试。')
        expected=day if stage in ('1135','1600','2130') else self.calendar.previous(day)
        run['quote_date']=str(expected)
        if stage in ('0730','0830','2130'):
            quotes=[Quote.model_validate(q) for q in previous.get('quotes',[])]
            factors=previous.get('factors',{}); membership=previous.get('membership',[])
            chart_path=self.output/'data/latest/charts.parquet'
            if chart_path.exists():
                try:
                    chart_rows=pd.read_parquet(chart_path)
                    chart_rows=chart_rows[pd.to_datetime(chart_rows.timestamp,utc=True)<=as_of]
                    for code,f in factors.items():
                        subset=chart_rows[chart_rows.stock_code==code].drop(columns='stock_code')
                        if not subset.empty and str(subset.timestamp.iloc[-1])[:10]==str(expected): f['bars']=clean(subset.to_dict('records'))
                except Exception as exc: run['warnings'].append('K线滚动缓存不可用，因子和筛选不受影响。')
            sectors=previous['sectors']; market=previous['market']
            run['data_quality']=previous['data_quality'].copy(); run['data_quality']['as_of_time']=as_of.isoformat()
            if any(q.timestamp>as_of or q.timestamp.astimezone(TZ).date()!=expected for q in quotes): raise ValueError('invalid predecessor quote time')
            basis = '初始化所用收盘行情' if run.get('bootstrap_origin') else '正式收盘快照'
            run['warnings'].append(f'行情沿用 {expected} {basis}；本阶段仅刷新事件。隔夜变量未接入，市场分为前收盘参考。')
            limit_pool=previous.get('limit_pool',[])
        else:
            universe=demo.universe if demo else self.collector.fetch('universe')
            def accept_quotes(rows):
                _, quality=validate_quotes(rows,as_of,expected,self.config,stage,max(len(universe),self.config['sources']['expected_universe_min']))
                if quality['status']=='RED': raise Unavailable('quote freshness or coverage failure')
                return rows
            raw=demo.quotes if demo else self.collector.fetch('quotes',codes=[u['code'] for u in universe],accept=accept_quotes)
            by_code={u['code']:u for u in universe}
            for q in raw: q.industry=q.industry or by_code.get(q.code,{}).get('industry')
            minimum=len(universe) if demo else max(len(universe),self.config['sources']['expected_universe_min'])
            quotes,quality=validate_quotes(raw,as_of,expected,self.config,stage,minimum)
            run['data_quality']=quality; run['universe_count']=len(universe); run['valid_quote_count']=len(quotes)
            market=market_score(quotes,self.config,quality)
            if quality['status']=='RED':
                run.update(market=market,status='DEGRADED'); run['warnings'].append('行情覆盖不足，市场不评级，候选池为空。'); return
            membership=demo.membership if demo else previous['membership'] if stage=='1135' else self.membership(quotes,as_of)
            initial=sector_scores(quotes,membership,{},self.config)
            good_ids={s['id'] for s in initial if s['state'] in self.config['sector']['allowed']}
            good_codes={c for s in membership if s['id'] in good_ids for c in s['codes']}
            if stage=='1135': wanted={s['stock_code'] for group in previous['pools'].values() for s in group}
            else:
                manual=read_json(self.project/'config/events.json',[])
                independent_codes=set()
                for e in manual:
                    try:
                        item=Event.model_validate(e)
                        if item.verified and item.publish_time<=as_of: independent_codes.add(item.stock_code)
                    except ValueError: pass
                wanted=good_codes|independent_codes
            selected=[q for q in sorted(quotes,key=lambda q:-q.amount) if q.code in wanted][:self.config['sources']['max_history_stocks']]
            factors={}; failures=[]
            def calculate(q):
                frame=demo.frames[q.code] if demo else self.collector.fetch('history',code=q.code,end=expected)
                frame=validate_bars(frame,as_of,self.config)
                if stage=='1135':
                    frame=frame[pd.to_datetime(frame.timestamp,utc=True).dt.date<day]
                    frame=pd.concat([frame,pd.DataFrame([{'timestamp':q.timestamp,'open':q.open,'high':q.high,'low':q.low,'close':q.price,'volume':q.volume,'amount':q.amount,'source':q.source}])],ignore_index=True)
                if len(frame)<self.config['quality']['required_bars']: raise ValueError('short history')
                if pd.Timestamp(frame.timestamp.iloc[-1]).astimezone(TZ).date()!=expected: raise ValueError('stale history')
                if abs(frame.close.iloc[-1]/q.price-1)*100>self.config['quality']['conflict_price_pct']: raise ValueError('history spot conflict')
                f=technical(frame,self.config['atr']['period']); f['history_source']=str(frame.source.iloc[0]); f['as_of_time']=as_of.isoformat()
                if stage=='1135':
                    for n in [5,10,20]: f[f'amount_ratio_{n}d']=None
                    f['volume_comparison_basis']='午盘缺同时间基准，量价比不计算'
                f['bars']=clean(frame.tail(self.config['storage']['max_snapshot_bars']).to_dict('records'))
                return q.code,f
            with ThreadPoolExecutor(max_workers=self.config['sources']['workers']) as executor:
                futures={executor.submit(calculate,q):q.code for q in selected}
                for future in as_completed(futures):
                    try:
                        code,f=future.result(); factors[code]=f
                    except Exception as exc: failures.append({'code':futures[future],'reason':'HISTORY_'+type(exc).__name__})
            run['eliminations'].extend(failures)
            run['data_quality']['history_coverage']=len(factors)/len(selected) if selected else 1.0
            run['funnel']={'universe':len(universe),'valid_quotes':len(quotes),'sector_pass':len(wanted),'history_budget':len(selected),'factor_ready':len(factors)}
            sectors=sector_scores(quotes,membership,factors,self.config); limit_pool=[]
            if stage=='1600':
                if demo: limit_pool=[{'code':q.code,'board_count':1,'source':'SIMULATED','trade_date':str(day)} for q in quotes if q.limit_up_price and abs(q.price-q.limit_up_price)<.0051]
                else:
                    try: limit_pool=self.collector.fetch('limit_pool',day=day)
                    except Unavailable: run['warnings'].append('涨停池不可用；仅依据明确涨停价判定，板数留空。')
            run['factor_count']=len(factors)
            run['warnings'].append(f"全市场快照经板块过滤，最多{self.config['sources']['max_history_stocks']}只历史日线；板块多日指标仅覆盖已采集成分。")
        preliminary=analyze_stocks(quotes,factors,sectors,membership,[],market,self.config,limit_pool)
        preliminary_pools,_=pools(preliminary,stage,self.config,previous)
        candidate_codes=[s['stock_code'] for s in sorted([s for g in preliminary_pools.values() for s in g],key=lambda s:-(s['total_score'] or 0))]
        events=[]
        for item in read_json(self.project/'config/events.json',[]):
            try: events.append(Event.model_validate(item))
            except ValueError: run['errors'].append({'module':'manual_events','error':'ValidationError'})
        if demo: events.extend(demo.events())
        else:
            for item in (previous or {}).get('events',[]):
                try: events.append(Event.model_validate({k:v for k,v in item.items() if k not in {'expectation','expectation_basis'}}))
                except ValueError: pass
            try: events.extend(self.announcements.fetch('events',codes=candidate_codes[:self.config['ai']['max_candidates']]))
            except Unavailable: run['warnings'].append('公告源不可用；仅保留已知事件。')
        event_rows=expectation(events,factors,as_of,self.config)
        stocks=analyze_stocks(quotes,factors,sectors,membership,event_rows,market,self.config,limit_pool)
        run['eliminations'] += [{'stock_code':s['stock_code'],'reason':s['exclusion_reason']} for s in stocks if s['position_type']=='排除']
        if stage=='1135':
            stocks=midday_validate(stocks,previous,market,self.config); seen={s['stock_code'] for s in stocks}
            missing=[{**s,'validation_label':'D 证伪','morning_return':None,'negative_factor':'午盘行情不足，不能确认'} for group in previous['pools'].values() for s in group if s['stock_code'] not in seen]
            run['validations']=stocks+missing
            if market.get('environment')!='强': run['afternoon_message']='今日午后不适合连板接力。'
        selected,changes=pools(stocks,stage,self.config,previous)
        if stage=='1135':
            selected={k:[s for s in v if s.get('validation_label','').startswith(('S','A','B'))] for k,v in selected.items()}
            if market.get('environment')!='强': selected['POOL_A']=[]
        for group in selected.values():
            for stock in group: stock.update(date=str(day),stage=stage)
        if stage in ('1135','1600'):
            mapped={c for sector in membership for c in sector['codes']}
            mapping_coverage=sum(q.code in mapped for q in quotes)/max(len(quotes),1)
            run['data_quality']['sector_mapping_coverage']=mapping_coverage
            if mapping_coverage<1: run['warnings'].append(f'板块成分映射覆盖 {mapping_coverage:.1%}；未映射股票排除，不能声称完成所有个股的板块分析。')
        run.update(pools=selected,market=market,sectors=sectors,events=event_rows,transitions=changes,membership=membership,limit_pool=limit_pool)
        counts=Counter(s['position_type'] for s in stocks)
        run['position_counts']={k:counts[k] for k in ['启动观察','趋势观察','高位观察','回调观察','排除']}
        for sector in sectors:
            for st in ['0830','1135','1600']:
                old=read_json(self.stage_path(day,st),{}); match=next((s for s in old.get('sectors',[]) if s['id']==sector['id']),None)
                if match: sector['history'][st]=match['score']
            sector['history'][stage]=sector['score']
        for group in selected.values():
            for s in group:
                for st in self.config['stages']:
                    old=read_json(self.stage_path(day,st),{})
                    match=next((x for g in old.get('pools',{}).values() for x in g if x['stock_code']==s['stock_code']),None)
                    if match: s['rank_history'].append({'date':str(day),'stage':st,'rank':match['rank'],'score':match['total_score']})
        run['missing_factors']=list(dict.fromkeys(market.get('missing_factors',[])+['龙虎榜席位归因','公告正文语义核验','历史复权事件校验','板块全部成分多日因子','消息发布前后因果验证']))
        if run['missing_factors'] and run['data_quality']['status']=='GREEN': run['data_quality']['status']='YELLOW'
        history_coverage=run['data_quality'].get('history_coverage',1)
        if history_coverage<self.config['sources']['min_history_coverage']:
            run['warnings'].append('历史数据覆盖低于阈值，停止发布候选。')
        if not sectors or history_coverage<self.config['sources']['min_history_coverage']:
            run['data_quality']['status']='RED'; run['warnings'].append('历史因子或板块映射不足，不发布候选。'); run['pools']={k:[] for k in selected}
        run['status']='DEGRADED' if run['data_quality']['status']=='RED' else 'COMPLETE'
        run['ai']={'status':'DEMO_DISABLED'} if demo else enhance(run['pools'],self.config,as_of)
        run['quotes']=[q.model_dump(mode='json') for q in quotes]; run['factors']=factors
        if run.get('bootstrap_origin'):
            run['missing_factors'] += ['初始化历史公告风险完整核验', '初始化当时行业成分快照']
            run['data_quality']['status'] = 'RED' if run['data_quality']['status']=='RED' else 'YELLOW'
            for group in run['pools'].values():
                for stock in group:
                    stock['negative_factor'] += '；初始化历史公告风险及当时行业归属未完整核验'
        try: run['evaluation']={} if run.get('bootstrap_origin') else update_outcomes(self.output,run,self.calendar,self.config)
        except Exception as exc: run['errors'].append({'module':'evaluation','error':type(exc).__name__})
    def finish(self, run):
        run['source_logs']=self.collector.logs+self.announcements.logs; logs=run['source_logs']
        run['source_success_rate']=sum(l['success'] for l in logs)/len(logs) if logs else None
        run['failed_sources']=sorted({l['source_name'] for l in logs if not l['success']})
        run['stock_count']=run.get('valid_quote_count',len(run.get('quotes',[]))); run['sector_count']=len(run.get('sectors',[])); run['candidate_count']=sum(map(len,run['pools'].values()))
        run['dashboard_updated_at']=datetime.now(TZ).isoformat(); run['finished_at']=datetime.now(TZ).isoformat()
        day=date.fromisoformat(run['date']); path=self.stage_path(day,run['stage']); path.parent.mkdir(parents=True,exist_ok=True)
        if run.get('factors'):
            rows=[{'stock_code':code,**{k:v for k,v in f.items() if k!='bars'}} for code,f in run['factors'].items()]
            try: pd.DataFrame(rows).to_parquet(path.parent/'factor_snapshot.parquet',index=False)
            except Exception as exc: run['errors'].append({'module':'factor_parquet','error':type(exc).__name__})
        if run['stage']=='1600' and run.get('quotes'):
            try: pd.DataFrame(run['quotes']).to_parquet(path.parent/'daily_quotes.parquet',index=False)
            except Exception as exc: run['errors'].append({'module':'daily_quote_parquet','error':type(exc).__name__})
        keep={s['stock_code'] for group in run['pools'].values() for s in group}
        run['quotes']=[q for q in run.get('quotes',[]) if q['code'] in keep]; run['factors']={k:v for k,v in run.get('factors',{}).items() if k in keep}
        chart_rows=[{'stock_code':code,**bar} for code,f in run['factors'].items() for bar in f.get('bars',[])]
        if chart_rows:
            chart_path=self.output/'data/latest/charts.parquet'; chart_path.parent.mkdir(parents=True,exist_ok=True)
            try: pd.DataFrame(chart_rows).to_parquet(chart_path,index=False)
            except Exception as exc: run['warnings'].append('K线缓存保存失败，已保留因子及报告。')
        text=stage_markdown(run); (path.parent/'report.md').write_text(text,encoding='utf-8')
        if self.mode=='live':
            outbox=DocsOutbox(self.output)
            if run['status']=='COMPLETE': outbox.enqueue(day,run['stage'],text)
            run['google_docs']=outbox.flush()
            if run['status']!='COMPLETE': run['google_docs']['current_report']='DEGRADED_LOCAL_ONLY'
        else: run['google_docs']={'status':'DEMO_DISABLED' if self.mode=='demo' else 'RETROSPECTIVE_SEPARATE'}
        history=copy.deepcopy(run)
        for f in history.get('factors',{}).values(): f.pop('bars',None)
        for group in history['pools'].values():
            for stock in group: stock.pop('bars',None)
        for stock in history.get('validations',[]): stock.pop('bars',None)
        write_json(path,history); write_json(path.parent/'candidates.json',history['pools'])
        dashboard=copy.deepcopy(run)
        dashboard.pop('factors',None); dashboard.pop('quotes',None); dashboard.pop('membership',None)
        write_json(self.output/'data/latest/latest.json',dashboard)
        write_json(self.output/'data/latest/run_status.json',{k:run[k] for k in ['run_id','date','stage','status','finished_at','warnings']})
        runs={st:read_json(self.stage_path(day,st)) for st in self.config['stages'] if self.stage_path(day,st).exists()}
        report=self.output/'reports'/f'{day}.md'; report.parent.mkdir(parents=True,exist_ok=True); report.write_text(daily_markdown(day,runs),encoding='utf-8')
        write_json(self.output/'reports/runs'/f"{run['run_id']}.json",{k:run.get(k) for k in ['run_id','date','stage','status','started_at','finished_at','source_success_rate','failed_sources','stock_count','sector_count','candidate_count','google_docs','dashboard_updated_at','errors']})
        return clean(run)
