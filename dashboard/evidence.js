'use strict';
// Source observations stay separate from qualified strategy candidates.
globalThis.MansonEvidence = {
 select(state, supplement, {demo=false,replay=false,now=Date.now()}={}) {
  if(demo||replay||['demo','retrospective'].includes(state.mode))return null;
  const day=state.quote_date;
  const validTime=t=>Number.isFinite(Date.parse(t))&&Date.parse(t)<=now;
  const formal=(state.limit_pool||[]).filter(r=>r.trade_date===day);
  const valid=supplement?.schema_version===1&&supplement.kind==='MARKET_EVIDENCE_SUPPLEMENT'
    &&supplement.trade_date===day&&validTime(supplement.observed_at)&&validTime(supplement.finished_at)
    &&Date.parse(supplement.observed_at)<=Date.parse(supplement.finished_at)
    &&Array.isArray(supplement.limit_pool)&&supplement.limit_pool.every(r=>r.trade_date===day);
  if(valid&&(!formal.length||Date.parse(supplement.finished_at)>Date.parse(state.as_of_time)))
   return {...supplement,supplement:true};
  if(formal.length||state.limit_evidence?.status==='AVAILABLE')return {
   trade_date:day,observed_at:state.as_of_time,finished_at:state.finished_at,
   limit_pool:formal,events:state.events||[],catalyst_evidence:state.catalyst_evidence||{},supplement:false};
  return null;
 },
 ladder(rows) {
  const groups={};
  for(const r of rows){const n=Number.isInteger(r.board_count)&&r.board_count>0?r.board_count:'未知';(groups[n]||=[]).push(r);}
  return Object.entries(groups).sort(([a],[b])=>(Number(b)||0)-(Number(a)||0));
 }
};
