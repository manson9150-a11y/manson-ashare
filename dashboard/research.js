'use strict';
// Presentation adapters never rewrite a frozen report or recompute its scores.
globalThis.MansonResearch = (() => {
 const stages={
  '0800':'08:00 盘前计划','1200':'12:00 午间验证','2200':'22:00 晚间复盘',
  '0730':'07:30 隔夜确认','0830':'08:30 盘前终审','1135':'11:35 午盘验证',
  '1600':'16:00 收盘扫描','2130':'21:30 晚间二筛'
 };
 const oldStages=new Set(['0730','0830','1135','1600','2130']);
 const labels={AVAILABLE:'可用',PARTIAL:'部分可用',UNAVAILABLE:'暂无有效数据',MANUAL:'需人工核验',NOT_INTEGRATED:'未接入模型 / 评分'};
 const numeric=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
 const ratio=v=>numeric(v)?Math.max(0,Math.min(1,Number(v))):null;
 const allCandidates=run=>Object.values(run.pools||{}).flat();
 function coverageText(value){
  if(value==null)return '未记录';
  if(typeof value==='string'&&!numeric(value))return value;
  if(typeof value==='object'){
   const n=value.available??value.accepted??value.covered??value.numerator;
   const d=value.total??value.expected??value.denominator;
   const r=value.ratio??value.coverage??(numeric(n)&&Number(d)>0?Number(n)/Number(d):null);
   return `${numeric(n)&&numeric(d)?`${n} / ${d} · `:''}${coverageText(r)}`;
  }
  const r=ratio(value);return r==null?'未记录':`${(r*100).toFixed(1).replace(/\.0$/,'')}%`;
 }
 function stageLabel(stage){return `${stages[stage]||stage||'阶段未记录'}${oldStages.has(String(stage))?'（历史阶段）':''}`;}
 function formatCondition(text){
  return String(text??'未记录').replace(/(-?\d+\.\d{4,})/g,n=>Number(n).toFixed(2));
 }
 function scoreCoverage(s){return ratio(s.score_coverage);}
 function boardLabel(s){
  if(Number.isInteger(s.board_count)&&s.board_count>0)return s.board_count===1?'首板晋级观察':`已连板 · ${s.board_count}板`;
  if(Number.isInteger(s.derived_board_count)&&s.derived_board_count>0)return `推导${s.derived_board_count}板 · 待核验`;
  return s.pool==='POOL_A'?'板数待核验':'';
 }
 function eventReview(s){
  const value=s.event_review_status;
  const known={VERIFIED:'已核验事实',VERIFIED_RULE:'已核验事实',PARTIAL:'部分事件待核验',PENDING:'事件待核验',NEEDS_REVIEW:'事件待核验',UNAVAILABLE:'事件覆盖待补',UNREVIEWED:'事件待核验',SUPPORTED_FACTS_VERIFIED:'已核验支持范围内事实',NOT_REVIEWED:'事件待核验',NO_EVENTS:'未发现已核验事件'};
  if(value)return known[value]||value;
  const events=s.events||[];
  if(!events.length)return '事件覆盖待补';
  return events.every(e=>e.verified)?'已核验事实':'事件待核验';
 }
 function notes(value){
  if(Array.isArray(value))return value.flatMap(notes);
  if(typeof value==='string')return value?[formatCondition(value)]:[];
  if(value&&typeof value==='object')return notes(value.reason??value.label??value.description??value.note??value.message);
  return [];
 }
 function eligibility(s){
  const provided=notes(s.eligibility_notes);
  if(provided.length)return [s.positive_factor?formatCondition(s.positive_factor):'入池理由未记录',...provided];
  return [s.positive_factor?formatCondition(s.positive_factor):'旧快照未记录完整入池条件',s.volume_type==='成交额历史缺失'?'成交额历史缺失，量价未计分':''].filter(Boolean);
 }
 function tradability(s){
  const basis=s.tradability_basis;
  const basisText=typeof basis==='object'?basis.description||basis.reason||basis.label:typeof basis==='string'?basis:null;
  const copied=!basis||basis==='NOT_ASSESSED'||/copy|copied|total_score|composite|proxy|综合|复制|rule_score/i.test(basisText||'');
  if(copied)return {independent:false,label:'交易约束待独立评估',reason:basis==='NOT_ASSESSED'?'尚未评估成交约束，不输出交易性分。':'原交易性字段沿用规则分，不能据此判断可成交性。',score:s.tradability_score};
  return {independent:true,label:'交易条件规则值',reason:basisText||'规则依据未记录，不代表实际可成交。',score:s.tradability_score};
 }
 function sectorPresentation(s){
  const coverage=ratio(s.factor_coverage??s.history_coverage);
  const total=numeric(s.member_count)?Number(s.member_count):null;
  const explicit=s.factor_member_count??s.valid_factor_count??s.factor_ready_count;
  const valid=numeric(explicit)?Number(explicit):coverage!=null&&total!=null?Math.round(coverage*total):null;
  const incomplete=coverage==null||coverage<1;
  const soften=s.state==='持续强势'&&(!s.score_basis&&incomplete||s.score_basis==='TODAY_BREADTH_MOMENTUM');
  return {label:soften?'当日强势':s.state||'待确认',original:soften?s.state:null,coverage,valid,total,
   note:soften?'原报告：持续强势；多日成分覆盖不足，展示按当日强度解释。':incomplete?'多日成分未完整覆盖。':'成分覆盖不等于策略已验证。'};
 }
 function quality(run){
  const q=run.data_quality||{},f=run.funnel||{};
  const candidates=allCandidates(run),covered=candidates.map(scoreCoverage).filter(v=>v!=null);
  const unique=[...new Set(covered)];
  const scoreLabel=!covered.length?'未记录':unique.length===1?coverageText(unique[0]):`${coverageText(Math.min(...covered))}–${coverageText(Math.max(...covered))}`;
  return [
   {label:'行情覆盖',value:coverageText(q.coverage),note:numeric(q.accepted)?`${q.accepted} 只有效行情`:'相对预期行情范围'},
   {label:'板块映射',value:coverageText(q.sector_mapping_coverage),note:'有板块归属的有效行情占比'},
   {label:'历史预算成功率',value:coverageText(q.history_coverage),note:numeric(f.history_budget)?`${f.factor_ready??'—'} / ${f.history_budget} 只预算内标的`:'仅针对已请求标的，非全市场历史覆盖'},
   {label:'候选计分覆盖',value:scoreLabel,note:covered.length?`${covered.length} / ${candidates.length} 条候选有记录；缺失权重可能重归一`:'未记录不代表完整覆盖'}
  ];
 }
 function factorStatuses(run,evidence,wudao){
  if(Array.isArray(run.factor_statuses)&&run.factor_statuses.length)return run.factor_statuses.map((r,i)=>({...r,id:r.id||`factor-${i}`,label:r.label||r.id||'未命名指标',status:labels[r.status]?r.status:'UNAVAILABLE',reason:r.reason||'本报告未记录原因'}));
  const limit=evidence?.limit_pool||run.limit_pool||[];
  const known=limit.filter(r=>Number.isInteger(r.board_count)&&r.board_count>0);
  const w=wudao||run.wudao;
  const money=(w?.featured?.rows||[]).some(r=>numeric(r.mainNetAmount));
  const missing=[...new Set([...(run.market?.missing_factors||[]),...(run.missing_factors||[])])];
  for(const label of ['首板/连板梯队','最高板高度/梯队完整度','主力资金'])if(!missing.includes(label))missing.push(label);
  return missing.map((label,i)=>{
   let status='UNAVAILABLE',reason='旧报告未记录对应计算结果，需后续正式任务补齐。',coverage=null,source='旧报告',time=run.as_of_time;
   if(/首板|最高板/.test(label)&&known.length){status='NOT_INTEGRATED';reason=`已有 ${known.length} 条板数记录；最高 ${Math.max(...known.map(r=>r.board_count))} 板。旧市场评分未接入，完整梯队覆盖仍需核验。`;coverage={available:known.length,total:limit.length};source=evidence?.supplement?'盘后补充涨停池':'正式涨停池';time=evidence?.observed_at||time;}
   else if(label==='主力资金'&&money){status='NOT_INTEGRATED';reason='已有板块主力净额；未覆盖全市场资金模型，未计入旧市场评分。';source='悟道题材快照';time=w.featured?.snapshot_time||time;}
   else if(/人工|复权|因果|龙虎榜/.test(label)){status='MANUAL';reason=/因果/.test(label)?'价格与消息的同期变化不能证明因果关系，需要独立证据。':/复权/.test(label)?'历史价格序列需与公司行动交叉核验。':'现有自动核验范围有限，需原始材料与人工复核。';}
   else if(/全部成分/.test(label)){status='PARTIAL';reason='部分成分已有多日因子；请查看各板块有效成分数，不能代表全部成分。';}
   else if(/全市场涨跌停价/.test(label)){status=limit.length?'PARTIAL':'UNAVAILABLE';reason='涨停池有局部证据，未证明全市场逐只涨跌停价均已覆盖。';}
   else if(/昨日|晋级|高位|情绪周期/.test(label)){reason='旧报告缺少跨交易日追踪结果；不能从当日涨停名单直接推断。';}
   else if(/成交额|指数/.test(label)){reason='旧报告未记录完整市场历史基线；个股或局部样本不能替代全市场指标。';}
   return {id:`legacy-${i}`,label,status,reason,coverage,source,as_of_time:time,used_in_score:false,legacy:true};
  });
 }
 function catalystDiagnostics(run,evidence){
  if(Array.isArray(run.catalyst_diagnostics))return run.catalyst_diagnostics.map(d=>({code:d.stock_code||d.code||'未记录代码',name:d.stock_name||d.name||'',passed:d.passed??d.eligible??false,reasons:notes(d.reasons||d.failed_conditions||d.reason||d.eligibility_notes)}));
  if(run.pools?.POOL_C?.length)return [];
  const events=(evidence?.events||run.events||[]).filter(e=>e.verified);
  return [...new Set(events.map(e=>e.stock_code).filter(Boolean))].map(code=>{
   const item=allCandidates(run).find(s=>(s.stock_code||s.code)===code);
   const rejected=(run.eliminations||[]).filter(s=>(s.stock_code||s.code)===code).flatMap(s=>notes(s.reason));
   const explicit=notes(item?.eligibility_notes);
   return {code,name:item?.stock_name||'',passed:false,reasons:rejected.length?rejected:explicit.length?explicit:['旧报告未保存该事件的逐项 C 池筛选诊断；事实已核验，未入池原因待正式任务记录。']};
  });
 }
 function evaluation(run){
  const source=run.evaluation||{};
  return Object.entries(source.results||source).filter(([,v])=>v&&typeof v==='object'&&v.sample_size>0).map(([key,v])=>({key,...v,legacy:oldStages.has(key.split('/')[0])||v.independent_days==null,definition:v.definition||source.definition||'旧报告未记录完整收益统计定义。',independent_days:v.independent_days??source.independent_days??null,window_start:v.window_start||source.window_start,window_end:v.window_end||source.window_end}));
 }
 return {stages,labels,oldStages,coverageText,stageLabel,formatCondition,scoreCoverage,boardLabel,eventReview,eligibility,tradability,sectorPresentation,quality,factorStatuses,catalystDiagnostics,evaluation};
})();
