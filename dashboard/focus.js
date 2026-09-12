'use strict';
globalThis.MansonFocus=(()=>{
 const groups={POOL_B:'短期强势',POOL_C:'独立催化',POOL_H:'高波动观察'};
 function overlay(run,extra){
  if(run.mode!=='live'||run.status!=='COMPLETE'||extra?.mode!=='live'||extra.base_run_id!==run.run_id||extra.quote_date!==run.quote_date||!extra.stock_research||!extra.pools||!Number.isFinite(Date.parse(extra.projection?.generated_at))||Date.parse(extra.projection.generated_at)<Date.parse(run.as_of_time)||Date.parse(extra.projection.generated_at)>Date.now())return run;
  return {...run,pools:extra.pools,stock_research:extra.stock_research,projection:extra.projection};
 }
 function items(run){return Object.entries(run.pools||{}).filter(([key])=>key in groups).flatMap(([pool,rows])=>rows.map(s=>({...s,pool})));}
 function matches(s,kind,query=''){
  const tag=kind==='all'||kind==='catalyst'&&(s.pool==='POOL_C'||s.independent_catalyst)||kind==='momentum'&&s.pool==='POOL_B'||kind==='volatile'&&s.pool==='POOL_H';
  return tag&&[s.stock_code,s.stock_name,s.sector,...(s.wudao_themes||[])].join(' ').toLowerCase().includes(query.trim().toLowerCase());
 }
 function legacy(s){return {headline:'旧版候选，尚无本版研究计划',conclusion:s.positive_factor||'请等待正式阶段生成个股分析。',basis:'LEGACY',
  price_plan:{status:'WAIT_DATA',label:'历史候选不倒填入场价',entry_zone:null,trigger:'旧报告未保存条件计划。'},
  catalyst:{headline:'旧报告事件仅作历史依据',conclusion:'没有当时生成的本版分析，不以当前判断替代。'},change:{label:'历史记录'}};}
 return {groups,overlay,items,matches,legacy};
})();
