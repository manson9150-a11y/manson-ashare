const {test}=require('node:test');
const assert=require('node:assert/strict');
require('../dashboard/evidence.js');
const {select,ladder}=globalThis.MansonEvidence;
const state={mode:'live',quote_date:'2026-09-08',as_of_time:'2026-09-08T21:45:00+08:00',limit_pool:[]};
const supplement={schema_version:1,kind:'MARKET_EVIDENCE_SUPPLEMENT',trade_date:'2026-09-08',observed_at:'2026-09-08T23:16:00+08:00',finished_at:'2026-09-08T23:18:00+08:00',limit_pool:[{code:'002403',trade_date:'2026-09-08',board_count:4}]};
const now=Date.parse('2026-09-09T07:40:00+08:00');
test('same-date supplement renders without changing frozen strategy state',()=>{
 const copy=JSON.stringify(state);assert.equal(select(state,supplement,{now}).limit_pool.length,1);assert.equal(JSON.stringify(state),copy);
});
test('next morning may show explicitly dated prior-close evidence',()=>{
 assert.equal(select({...state,as_of_time:'2026-09-09T07:30:00+08:00'},supplement,{now}).supplement,true);
});
test('different date, future observations, demo and historical replay never mix',()=>{
 assert.equal(select({...state,quote_date:'2026-09-09'},supplement,{now}),null);
 assert.equal(select(state,supplement,{now:Date.parse(state.as_of_time)}),null);
 assert.equal(select(state,supplement,{now,replay:true}),null);
 assert.equal(select(state,supplement,{now,demo:true}),null);
 assert.equal(select({...state,mode:'retrospective'},supplement,{now}),null);
 assert.equal(select(state,{...supplement,limit_pool:[{trade_date:'2026-09-07'}]},{now}),null);
});
test('new formal observations replace older supplementary ones',()=>{
 const result=select({...state,as_of_time:'2026-09-09T07:30:00+08:00',limit_pool:[{code:'600865',trade_date:'2026-09-08',board_count:4}]},supplement,{now});
 assert.equal(result.supplement,false);assert.equal(result.limit_pool[0].code,'600865');
});
test('unknown vendor board count is not promoted from a derived count',()=>{
 const groups=ladder([{board_count:4},{board_count:2},{board_count:1},{board_count:null,derived_board_count:5}]);
 assert.deepEqual(groups.map(([n])=>n),['4','2','1','未知']);
});
