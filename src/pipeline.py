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
from src.collectors.wudao import WudaoResearch
from src.collectors.public import EastmoneyAdapter, TencentAdapter, SinaAdapter
from src.collectors.baostock import BaoStockAdapter
from src.collectors.announcements import AnnouncementAdapter, CninfoAnnouncementAdapter
from src.normalizers.quality import validate_quotes, validate_bars
from src.factors.technical import technical
from src.market.engine import market_score
from src.sectors.engine import sector_scores
from src.stocks.engine import analyze_stocks
from src.catalysts.engine import expectation, independent
from src.catalysts.evidence import CatalystEvidence
from src.collectors.limit_evidence import near_limit, enrich_limits
from src.collectors.market_history import HistoryStore, build_market_context
from src.screening.pools import predecessor, pools, midday_validate
from src.reports.render import stage_markdown, daily_markdown
from src.google_docs.writer import DocsOutbox
from src.ai.analyst import enhance
from src.evaluation.engine import update_outcomes

class Pipeline:
    def __init__(self, project, output=None, mode='live', config=None):
        self.project=Path(project).resolve(); self.output=Path(output or project).resolve(); self.mode=mode
        self.config=config or yaml.safe_load((self.project/'config/settings.yaml').read_text())
        self.wudao=WudaoResearch(self.config, cache_path=self.output/'data/latest/wudao_membership_cache.json')
        self.calendar=TradingCalendar(self.project/'config/calendar.json')
        self.collector=Collector([c(self.config) for c in [EastmoneyAdapter,TencentAdapter,SinaAdapter,BaoStockAdapter] if c.source_name in self.config['sources']['enabled']])
        self.history_store=HistoryStore(self.output,self.collector,self.config)
        self.announcements=Collector([CninfoAnnouncementAdapter(self.config, self.output/'data/latest/announcement_first_seen.json'), AnnouncementAdapter(self.config)])
    def stage_path(self, day, stage):
        return self.output/'data/history'/day.strftime('%Y/%m/%d')/stage/'stage_results.json'
    def event_cutoff(self, run, as_of, observed=None):
        """Actual live observation cutoff, separate from the frozen quote cutoff."""
        observed=observed or datetime.now(TZ)
        deadline=datetime.fromisoformat(f"{run['date']}T{self.config['stages'][run['stage']]['deadline']}:00").replace(tzinfo=TZ)
        if self.mode=='live' and observed.date().isoformat()==run['date']:
            as_of=max(as_of,min(observed,deadline))
        run['event_cutoff_time']=as_of.isoformat()
        return as_of
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
        weekend_target = self.config.get('weekend_evenings', {}).get(str(day)) if self.mode=='live' and stage=='2130' else None
        if not trading and not weekend_target: return self.status_only(run,'NON_TRADING_DAY','休市；未采集或生成伪行情报告')
        if self.mode=='live':
            deadline=datetime.fromisoformat(f"{day}T{self.config['stages'][stage]['deadline']}:00").replace(tzinfo=TZ)
            if now.date()!=day or now<as_of or now>deadline:
                return self.status_only(run,'OUTSIDE_STAGE_WINDOW','超出阶段时间窗。历史阶段只可读取已保存快照，不能用当前接口倒填。')
        run['schedule_version']=2 if stage in ('0800','1200','2200') else 1
        run['scheduled_for']=as_of.isoformat()
        if self.mode=='live':
            run['schedule_delay_seconds']=(now-as_of).total_seconds()
            as_of=now
            run['as_of_time']=as_of.isoformat()
        existing=read_json(self.stage_path(day,stage))
        if existing and existing.get('status')=='COMPLETE':
            existing['google_docs']=DocsOutbox(self.output).flush() if self.mode=='live' else {'status':'DEMO_DISABLED'}
            return existing
        if not trading and weekend_target:
            return self.weekend_evening(run, day, date.fromisoformat(weekend_target), as_of)
        previous=None; key=predecessor(day,stage,self.calendar)
        if key:
            previous=read_json(self.stage_path(*key))
            if previous is None and stage in ('0800','1200'):
                # One-way migration: frozen legacy close evidence, never reconstruct a missed morning.
                for legacy in (('2130','1600') if stage=='0800' else ('0830',)):
                    candidate=read_json(self.stage_path(key[0],legacy))
                    if candidate and candidate.get('status')=='COMPLETE':
                        previous=candidate; key=(key[0],legacy); break
            initialization = None
            if previous is None and self.mode == 'live' and stage in ('0730','0800'):
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
    def weekend_evening(self, run, day, target, as_of):
        from src.bootstrap import load_seed
        previous = load_seed(self.output, target, as_of, self.calendar, self.config)
        if not previous:
            return self.status_only(run, 'MISSING_PREDECESSOR', '周末晚间二筛缺少有效初始化快照。')
        market_day = self.calendar.previous(target)
        run['stage_label'] = '周末晚间二筛'
        run['weekend_review'] = {'market_date': str(market_day), 'next_trading_date': str(target)}
        run['bootstrap_origin'] = copy.deepcopy(previous['bootstrap_origin'])
        run['predecessor'] = {'date': previous['date'], 'stage': 'BOOTSTRAP', 'run_id': previous['run_id']}
        run['warnings'] = [f'周末晚间研究：行情沿用{market_day}收盘，按本次实际研究截点刷新公告并二筛；不生成休市日行情。',
                           '承接初始化名单，仅筛选已有候选；事后行业分类和历史公告风险缺口仍保留，本轮不计入常规效果统计。']
        try:
            self.compute(run, market_day, '2130', as_of, copy.deepcopy(previous))
            for group in run['pools'].values():
                for stock in group:
                    stock['date'] = str(day)
        except Exception as exc:
            run.update(status='DEGRADED', data_quality={'status':'RED'})
            run['errors'].append({'module':'weekend_evening','error':type(exc).__name__})
            run['warnings'].append('周末二筛失败，保留之前的初始化快照。')
            run['pools']={k:[] for k in run['pools']}
        result = self.finish(run)
        if result['status'] == 'COMPLETE':
            seed = copy.deepcopy(result)
            seed.update(mode='bootstrap', status='BOOTSTRAP_READY')
            seed['bootstrap_origin'].update(created_at=seed['as_of_time'], weekend_evening_run_id=seed['run_id'])
            write_json(self.output/'data/bootstrap'/f'{target}.json', seed)
        return result
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
    def stock_factors(self, q, expected, as_of, stage, demo=None):
        history_end=self.calendar.previous(expected) if stage in ('1135','1200') else expected
        def accept_history(frame):
            if stage not in ('1135','1200') and abs(frame.close.iloc[-1]/q.price-1)*100>self.config['quality']['conflict_price_pct']:
                raise Unavailable('history spot conflict')
            return frame
        frame=demo.frames[q.code] if demo else self.history_store.fetch(q.code,history_end,as_of,accept=accept_history,quote=q if stage not in ('1135','1200') else None,previous_trade_day=self.calendar.previous(history_end))
        frame=validate_bars(frame,as_of,self.config)
        if stage in ('1135','1200'):
            frame=frame[pd.to_datetime(frame.timestamp,utc=True).dt.date<as_of.date()]
            frame=pd.concat([frame,pd.DataFrame([{'timestamp':q.timestamp,'open':q.open,'high':q.high,'low':q.low,'close':q.price,'volume':q.volume,'amount':q.amount,'source':q.source}])],ignore_index=True)
        if len(frame)<self.config['quality']['required_bars']: raise ValueError('short history')
        if pd.Timestamp(frame.timestamp.iloc[-1]).astimezone(TZ).date()!=expected: raise ValueError('stale history')
        if abs(frame.close.iloc[-1]/q.price-1)*100>self.config['quality']['conflict_price_pct']: raise ValueError('history spot conflict')
        f=technical(frame,self.config['atr']['period']); f['history_source']=str(frame.source.iloc[0]); f['as_of_time']=as_of.isoformat()
        if stage in ('1135','1200'):
            for n in [5,10,20]: f[f'amount_ratio_{n}d']=None
            f['volume_comparison_basis']='午盘缺同时间基准，量价比不计算'
        f['bars']=clean(frame.tail(self.config['storage']['max_snapshot_bars']).to_dict('records'))
        return q.code,f

    def compute(self, run, day, stage, as_of, previous):
        demo=None
        if self.mode=='demo':
            from src.collectors.demo import DemoData
            demo=DemoData(self.calendar,as_of,stage)
            run['warnings'].append('DEMO / 模拟数据：所有企业、事件和评分仅用于流程测试。')
        expected=day if stage in ('1135','1600','2130','1200','2200') else self.calendar.previous(day)
        run['quote_date']=str(expected)
        if self.mode=='live' and self.config.get('wudao',{}).get('enabled',False):
            run['wudao']=self.wudao.collect(expected,as_of,stage)
            if run['wudao']['status']!='OK':
                run['warnings'].append('悟道采集未完整成功：'+','.join(run['wudao']['errors'])+'；可用数据明确展示，其余沿用原接口，不能声称已覆盖全市场题材。')
            run['warnings'].append('悟道热点按题材强度和行业涨幅展示；系统规则分独立计算。前十题材成分为当前分类，仅用于本次及后续研究。')
        evidence=None
        event_as_of=as_of
        events=[]
        for item in read_json(self.project/'config/events.json',[])+(previous or {}).get('events',[]):
            try: events.append(Event.model_validate({k:v for k,v in item.items() if k not in {'expectation','expectation_basis'}}))
            except ValueError: run['errors'].append({'module':'events','error':'ValidationError'})
        if demo:
            events.extend(demo.events())
        elif self.config.get('catalyst_evidence',{}).get('enabled',False):
            evidence=CatalystEvidence(self.config,self.output)
            cached=evidence.cached_events(as_of)
            events.extend(cached)
            evidence.status['cached_verified_events']=len(cached)
            if stage not in ('1135','1200'): events.extend(evidence.discover(as_of))
            event_as_of=self.event_cutoff(run,as_of)
            events=evidence.verify(events,event_as_of)
            run['catalyst_evidence']=evidence.status
            run['evidence_logs']=evidence.logs
        early_events=expectation(events,{},event_as_of,self.config)
        independent_codes={e['stock_code'] for e in early_events if independent(e,self.config)}
        if stage in ('0730','0830','2130','0800'):
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
            run['market_context']=copy.deepcopy(previous.get('market_context',{}))
            run['data_quality']=previous['data_quality'].copy(); run['data_quality']['as_of_time']=as_of.isoformat()
            if any(q.timestamp>as_of or q.timestamp.astimezone(TZ).date()!=expected for q in quotes): raise ValueError('invalid predecessor quote time')
            basis = '初始化所用收盘行情' if run.get('bootstrap_origin') else '正式收盘快照'
            run['warnings'].append(f'行情沿用 {expected} {basis}；本阶段刷新事件与悟道热点参考。隔夜变量未接入，市场分为前收盘参考。')
            limit_pool=previous.get('limit_pool',[])
            run['limit_evidence']=copy.deepcopy(previous.get('limit_evidence',{'status':'UNKNOWN','note':'前序未记录涨停证据覆盖；等待新一轮收盘扫描。'}))
            # Fresh, verified events may introduce C names from the frozen full-market
            # close archive. No live quotes are used to reconstruct a premarket price.
            wanted_new=independent_codes-{q.code for q in quotes}
            if wanted_new:
                archive=self.stage_path(expected,'2200').parent/'daily_quotes.parquet'
                if not archive.exists(): archive=self.stage_path(expected,'1600').parent/'daily_quotes.parquet'
                if archive.exists():
                    archived=clean(pd.read_parquet(archive).to_dict('records'))
                    candidates=[Quote.model_validate(q) for q in archived if q['code'] in wanted_new]
                    for q in candidates[:self.config.get('catalyst_evidence',{}).get('max_new_candidates',20)]:
                        if q.timestamp>as_of or q.timestamp.astimezone(TZ).date()!=expected: continue
                        try:
                            code,f=self.stock_factors(q,expected,as_of,stage,demo)
                            quotes.append(q); factors[code]=f
                        except Exception as exc:
                            run['warnings'].append('独立事件候选历史不足：'+q.code+' '+type(exc).__name__)
                else: run['warnings'].append('缺少完整收盘行情存档，名单外独立事件等待下次收盘验证。')
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
            membership=demo.membership if demo else previous['membership'] if stage in ('1135','1200') else self.membership(quotes,as_of)
            additions=run.get('wudao',{}).get('membership',[])
            new_ids={s['id'] for s in additions}
            membership=additions+[s for s in membership if s['id'] not in new_ids]
            initial=sector_scores(quotes,membership,{},self.config)
            good_ids={s['id'] for s in initial if s['state'] in self.config['sector']['allowed']}
            good_codes={c for s in membership if s['id'] in good_ids for c in s['codes']}
            limit_pool=[]
            if stage in ('1600','2200','1135','1200'):
                if demo:
                    limit_pool=[{'code':q.code,'board_count':1,'limit_up_price':q.limit_up_price,'source':'SIMULATED','trade_date':str(day)} for q in quotes if q.limit_up_price and abs(q.price-q.limit_up_price)<.0051]
                else:
                    try: limit_pool=self.collector.fetch('limit_pool',day=day)
                    except Unavailable: run['warnings'].append('涨停池源不可用或返回未核验空表；尝试明确涨停价及保守日线规则，不把空表当作无涨停。')
            limit_codes={r['code'] for r in limit_pool}|{q.code for q in quotes if near_limit(q)}
            if stage in ('1135','1200'): wanted={s['stock_code'] for group in previous['pools'].values() for s in group}
            else: wanted=good_codes|independent_codes|limit_codes
            # Reserve history for A/C identities before filling the trend budget.
            selected=sorted([q for q in quotes if q.code in wanted],
                key=lambda q:(0 if q.code in independent_codes else 1 if q.code in limit_codes else 2,-q.amount))[:self.config['sources']['max_history_stocks']]
            factors={}; failures=[]
            def calculate(q):
                return self.stock_factors(q,expected,as_of,stage,demo)
            with ThreadPoolExecutor(max_workers=self.config['sources']['workers']) as executor:
                futures={executor.submit(calculate,q):q.code for q in selected}
                for future in as_completed(futures):
                    try:
                        code,f=future.result(); factors[code]=f
                    except Exception as exc: failures.append({'code':futures[future],'reason':'HISTORY_'+type(exc).__name__})
            run['eliminations'].extend(failures)
            run['data_quality']['history_coverage']=len(factors)/len(selected) if selected else 1.0
            run['funnel']={'universe':len(universe),'valid_quotes':len(quotes),'sector_pass':len(wanted),'history_budget':len(selected),'factor_ready':len(factors)}
            sectors=sector_scores(quotes,membership,factors,self.config)
            if not demo and stage in ('1600','2200'):
                limit_pool,run['limit_evidence']=enrich_limits(quotes,factors,limit_pool,day,self.calendar)
            elif stage in ('1135','1200'):
                run['limit_evidence']=copy.deepcopy(previous.get('limit_evidence',{'status':'UNKNOWN'}))
            else:
                run['limit_evidence']={'status':'SIMULATED','identified':len(limit_pool)}
            run['factor_count']=len(factors)
            run['warnings'].append(f"全市场快照经板块过滤，最多{self.config['sources']['max_history_stocks']}只历史日线；板块多日指标仅覆盖已采集成分。")
        if stage in ('1600','2200','1135','1200'):
            if not demo:
                try:
                    run['market_context']=build_market_context(quotes,limit_pool,self.collector,self.config,self.output,self.calendar,day,as_of,persist=stage in ('1600','2200'),limit_evidence=run.get('limit_evidence'),quality=run['data_quality'])
                except Exception as exc:
                    run['market_context']={'factor_statuses':[],'error':type(exc).__name__}
                    run['warnings'].append('增强市场证据暂不可用；基础行情与规则分保留。')
            market=market_score(quotes,self.config,run['data_quality'],limit_pool=limit_pool,context=run.get('market_context'))
        preliminary=analyze_stocks(quotes,factors,sectors,membership,expectation(events,factors,event_as_of,self.config),market,self.config,limit_pool)
        preliminary_pools,_=pools(preliminary,stage,self.config,previous)
        candidate_codes=[s['stock_code'] for s in sorted([s for g in preliminary_pools.values() for s in g],key=lambda s:-(s['total_score'] or 0))]
        if not demo:
            try: events.extend(self.announcements.fetch('events',codes=candidate_codes))
            except Unavailable: run['warnings'].append('候选公告源不可用；保留独立发现与已知事件。')
            event_as_of=self.event_cutoff(run,event_as_of)
            if evidence:
                # One bounded PDF budget per stage; refresh only previously unread entries.
                events=evidence.verify(events,event_as_of)
                run['catalyst_evidence']=evidence.status
        if run.get('weekend_review'):
            observed = datetime.now(TZ)
            if observed.date() == date.fromisoformat(run['date']):
                as_of = max(as_of, observed)
                run['as_of_time'] = as_of.isoformat()
        event_rows=expectation(events,factors,event_as_of,self.config)
        date_only=sum(e.publish_time_precision=='date' for e in events)
        if date_only:
            run['warnings'].append(f'公告列表中{date_only}条仅精确到日期：当天记录须在研究截点前已被系统观察才纳入；首次观察时间独立保存，不冒充发布时间。标题分类仍须正文核验。')
        stocks=analyze_stocks(quotes,factors,sectors,membership,event_rows,market,self.config,limit_pool)
        run['eliminations'] += [{'stock_code':s['stock_code'],'reason':s['exclusion_reason']} for s in stocks if s['position_type']=='排除']
        if stage in ('1135','1200'):
            stocks=midday_validate(stocks,previous,market,self.config); seen={s['stock_code'] for s in stocks}
            missing=[{**s,'validation_label':'D 证伪','morning_return':None,'negative_factor':'午盘行情不足，不能确认'} for group in previous['pools'].values() for s in group if s['stock_code'] not in seen]
            run['validations']=stocks+missing
            if market.get('environment')!='强': run['afternoon_message']='今日午后不适合连板接力。'
        selected,changes=pools(stocks,stage,self.config,previous)
        if stage in ('1135','1200'):
            selected={k:[s for s in v if s.get('validation_label','').startswith(('S','A','B'))] for k,v in selected.items()}
            if market.get('environment')!='强': selected['POOL_A']=[]
        for group in selected.values():
            for stock in group: stock.update(date=str(day),stage=stage)
        if stage in ('1135','1600','1200','2200'):
            mapped={c for sector in membership for c in sector['codes']}
            mapping_coverage=sum(q.code in mapped for q in quotes)/max(len(quotes),1)
            run['data_quality']['sector_mapping_coverage']=mapping_coverage
            if mapping_coverage<1: run['warnings'].append(f'板块成分映射覆盖 {mapping_coverage:.1%}；未映射且无已核验独立事件的股票排除，不能声称完成所有个股的板块分析。')
        run.update(pools=selected,market=market,sectors=sectors,events=event_rows,transitions=changes,membership=membership,limit_pool=limit_pool)
        identified=sum(s['is_limit_up'] for s in stocks)
        le=run.get('limit_evidence',{})
        ce=run.get('catalyst_evidence',{})
        run['pool_diagnostics']={
            'POOL_A': {'status':'AVAILABLE' if selected['POOL_A'] else 'DATA_INCOMPLETE' if le.get('status') not in ('AVAILABLE','SIMULATED') else 'NO_MATCH',
                'identified':identified,'selected':len(selected['POOL_A']),'evidence':le},
            'POOL_C': {'status':'AVAILABLE' if selected['POOL_C'] else 'NEEDS_VERIFICATION' if not ce.get('verified') else 'NO_MATCH',
                'verified_events':ce.get('verified',sum(e['verified'] for e in event_rows)), 'selected':len(selected['POOL_C']),'evidence':ce}}
        run['pool_notes']={
            'POOL_A':f"识别涨停线索 {identified} 只，入选 {len(selected['POOL_A'])} 只。供应商板数与日线推导板数分别展示；缺少证据不能解释为市场无涨停。"+("本阶段验证前序名单，新候选由22:00晚间完整扫描建立。" if stage not in ('1600','2200') else ''),
            'POOL_C':f"限定公告扫描：发现 {ce.get('discovered',0)} 条，正文读取 {ce.get('documents_read',0)} 份，已核验事件 {sum(e['verified'] for e in event_rows)} 条，入选 {len(selected['POOL_C'])} 只。支持重大已签合同及正向业绩预告的明确量化事实；其他类型或歧义留待人工复核。"}
        counts=Counter(s['position_type'] for s in stocks)
        run['position_counts']={k:counts[k] for k in ['启动观察','趋势观察','高位观察','回调观察','排除']}
        for sector in sectors:
            for st in (['0800','1200','2200'] if stage in ('0800','1200','2200') else ['0830','1135','1600']):
                old=read_json(self.stage_path(day,st),{}); match=next((s for s in old.get('sectors',[]) if s['id']==sector['id']),None)
                if match: sector['history'][st]=match['score']
            sector['history'][stage]=sector['score']
        for group in selected.values():
            for s in group:
                s['wudao_themes']=[m['name'] for m in run.get('wudao',{}).get('membership',[]) if s['stock_code'] in m['codes']]
                for st in self.config['stages']:
                    old=read_json(self.stage_path(day,st),{})
                    match=next((x for g in old.get('pools',{}).values() for x in g if x['stock_code']==s['stock_code']),None)
                    if match: s['rank_history'].append({'date':str(day),'stage':st,'rank':match['rank'],'score':match['total_score']})
        from src.factors.availability import factor_statuses
        all_candidates=[s for group in selected.values() for s in group]
        run['data_quality']['candidate_score_coverage']=sum(s.get('score_coverage',0) for s in all_candidates)/len(all_candidates) if all_candidates else None
        run['data_quality']['candidate_amount_coverage']=sum(s.get('amount_ratio_5d') is not None for s in all_candidates)/len(all_candidates) if all_candidates else None
        run['data_quality']['history_requested_count']=run.get('funnel',{}).get('history_budget',len(factors))
        run['data_quality']['history_ready_count']=len(factors)
        run['data_quality']['history_coverage_scope']='本次查询预算；不是全市场历史覆盖'
        run['position_validation']={'startup':'AVAILABLE' if any(f.get('amount_ratio_5d') is not None for f in factors.values()) else 'VOLUME_UNAVAILABLE',
                                    'pullback':'AVAILABLE' if any(f.get('amount_ratio_5d') is not None for f in factors.values()) else 'VOLUME_UNAVAILABLE'}
        stock_map={s['stock_code']:s for s in stocks}
        picked={s['stock_code'] for group in selected.values() for s in group}
        run['catalyst_diagnostics']=[]
        for code in sorted({e['stock_code'] for e in event_rows if e.get('verified')}):
            stock=stock_map.get(code)
            reasons=[]
            if not stock: reasons=['缺少本阶段有效行情或历史因子，不能确认入池']
            elif stock.get('exclusion_reason'): reasons=[stock['exclusion_reason']]
            elif not stock.get('independent_catalyst'): reasons=['事件新鲜度、可靠性或独立催化条件未满足']
            elif stock.get('total_score') is None or stock['total_score']<self.config['candidate_pool']['min_score']: reasons=['规则分未达到入池门槛']
            elif code in picked and code not in {s['stock_code'] for s in selected['POOL_C']}: reasons=['已按涨停或趋势规则进入 A / B 池，候选池互斥，不重复计入 C 池']
            elif code not in picked: reasons=['阶段规则或候选数量上限未通过；已核验事实不自动入池']
            run['catalyst_diagnostics'].append({'stock_code':code,'stock_name':stock.get('stock_name',code) if stock else code,'passed':any(s['stock_code']==code for s in selected['POOL_C']),'reasons':reasons})
        history_coverage=run['data_quality'].get('history_coverage',1)
        if history_coverage<self.config['sources']['min_history_coverage']:
            run['warnings'].append('历史数据覆盖低于阈值，停止发布候选。')
        if not sectors or history_coverage<self.config['sources']['min_history_coverage']:
            run['data_quality']['status']='RED'; run['warnings'].append('历史因子或板块映射不足，不发布候选。'); run['pools']={k:[] for k in selected}
            run['data_quality'].update(candidate_score_coverage=None,candidate_amount_coverage=None)
            for item in run['catalyst_diagnostics']:
                item.update(passed=False,reasons=item['reasons']+['本轮数据质量未达发布标准'])
        run['factor_statuses']=factor_statuses(run)
        run['missing_factors']=[x['label'] for x in run['factor_statuses'] if x['status']!='AVAILABLE']
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
        run['source_logs']=self.collector.logs+self.announcements.logs+self.wudao.logs+run.get('evidence_logs',[]); logs=run['source_logs']
        run['source_success_rate']=sum(l['success'] for l in logs)/len(logs) if logs else None
        run['failed_sources']=sorted({l['source_name'] for l in logs if not l['success']})
        run['stock_count']=run.get('valid_quote_count',len(run.get('quotes',[]))); run['sector_count']=len(run.get('sectors',[])); run['candidate_count']=sum(map(len,run['pools'].values()))
        run['dashboard_updated_at']=datetime.now(TZ).isoformat(); run['finished_at']=datetime.now(TZ).isoformat()
        from src.utils.calendar import next_scheduled_time
        run['next_scheduled_at']=next_scheduled_time(datetime.fromisoformat(run['finished_at']),self.calendar,self.config)
        run['active_schedule']=[{'stage':st,**self.config['stages'][st]} for st in self.config.get('active_stages',['0800','1200','2200'])]
        day=date.fromisoformat(run['date']); path=self.stage_path(day,run['stage']); path.parent.mkdir(parents=True,exist_ok=True)
        if run.get('factors'):
            rows=[{'stock_code':code,**{k:v for k,v in f.items() if k!='bars'}} for code,f in run['factors'].items()]
            try: pd.DataFrame(rows).to_parquet(path.parent/'factor_snapshot.parquet',index=False)
            except Exception as exc: run['errors'].append({'module':'factor_parquet','error':type(exc).__name__})
        if run['stage'] in ('1600','2200') and run.get('quotes'):
            try: pd.DataFrame(run['quotes']).to_parquet(path.parent/'daily_quotes.parquet',index=False)
            except Exception as exc: run['errors'].append({'module':'daily_quote_parquet','error':type(exc).__name__})
        keep={s['stock_code'] for group in run['pools'].values() for s in group}
        quote_names={q['code']:q['name'] for q in run.get('quotes',[])}
        run['limit_pool']=[{**row,'name':quote_names.get(row['code'],row.get('name',''))}
                           for row in run.get('limit_pool',[])]
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
