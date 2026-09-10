'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (value, digits=2) => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(digits);
const pct = value => value == null ? '—' : `${Number(value)>0?'+':''}${num(value)}%`;
const color = value => Number(value)>0?'positive':Number(value)<0?'negative':'';
const positions=['启动观察','趋势观察','高位观察','回调观察','排除'];
const demo=new URLSearchParams(location.search).get('demo')==='1';
const replayParam=new URLSearchParams(location.search).get('replay');
const replayDate=!demo&&/^\d{4}-\d{2}-\d{2}$/.test(replayParam||'')?replayParam:null;
let wudaoSupplement=null;
let evidenceSupplement=null,marketEvidence=null;
let state={},activePool='POOL_A',downloadURL,loadError=null;
const research=MansonResearch;
function pill(label){return `<span class="pill ${/高位|高|极端|退潮|转弱/.test(label)?'red':/启动|中|警告/.test(label)?'orange':''}">${esc(label)}</span>`;}
async function load(){
 $('refresh').disabled=true;wudaoSupplement=null;evidenceSupplement=null;loadError=null;
 try{
  const response=await fetch(`data/${demo?'demo':replayDate?`replays/${replayDate}`:'latest'}.json`,{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP_${response.status}`);
  const payload=await response.json();
  if(!payload||typeof payload!=='object'||!payload.pools)throw new Error('INVALID_REPORT');
  state=payload;
  if(!demo && state.mode==='demo')throw new Error('DEMO_IN_PRODUCTION');
  if(replayDate&&(state.mode!=='retrospective'||state.date!==replayDate))throw new Error('REPLAY_MISMATCH');
  if(!replayDate&&!demo&&state.mode==='retrospective')throw new Error('REPLAY_IN_PRODUCTION');
  if(replayDate&&!(state.pools?.[activePool]?.length)){
   activePool=Object.keys(state.pools||{}).find(k=>state.pools[k].length)||'POOL_A';
   document.querySelectorAll('[data-pool]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.pool===activePool)));
  }
 }catch(error){
  loadError=`${replayDate?'历史复盘':'正式报告'}读取失败（${error.message||'网络错误'}）。可点击刷新重试；读取失败不表示任务尚未运行。`;
  state={mode:replayDate?'retrospective':'live',status:'LOAD_FAILED',pools:{POOL_A:[],POOL_B:[],POOL_C:[]},market:{},sectors:[],data_quality:{status:'UNAVAILABLE'},warnings:[loadError]};
 }
 if(!demo&&!replayDate&&!state.wudao){try{
  const r=await fetch('data/wudao.json',{cache:'no-store'});
  if(r.ok){const w=await r.json();if(w.trade_date===state.quote_date&&Date.parse(w.requested_at)>=Date.parse(state.as_of_time))wudaoSupplement=w;}
 }catch{}}
 if(!demo&&!replayDate){try{
  const r=await fetch('data/evidence_supplement.json',{cache:'no-store'});
  if(r.ok)evidenceSupplement=await r.json();
 }catch{}}
 render();
 $('run-banner').hidden=!loadError;$('run-banner').textContent=loadError||'';
 if(!demo&&!replayDate){try{const r=await fetch('data/run_status.json',{cache:'no-store'});if(r.ok){const s=await r.json();if(s.status!=='COMPLETE'&&!loadError){$('run-banner').hidden=false;$('run-banner').textContent=`最近任务：${s.date} ${research.stageLabel(s.stage)} · ${s.status}。${(s.warnings||[]).join(' ')}`;}}}catch{}}
 $('refresh').disabled=false;
}
function beijingTime(value){
 const d=new Date(value);
 return value&&Number.isFinite(d.getTime())?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d)+'（北京时间）':'不可用';
}
function wudaoError(code){return ({MEMBER_REQUEST_BUDGET:'本次成分请求预算用完，未查询项保留缺口',MEMBERS_TIME_UNKNOWN:'部分成分缺少更新时间',TRUNCATED_MEMBERS:'部分题材成分返回不完整',MEMBERS_TIME_INVALID:'部分成分时间不符合要求',DATE_MISMATCH:'返回交易日不符',STALE_INTRADAY:'午盘快照过旧',HTTP_429:'接口限流',DAILY_LIMIT_EXCEEDED:'今日接口额度已用完',FREE_TIER_MARKET_OPEN_RESTRICTED:'接口开盘时段受限',NOT_CONFIGURED:'尚未配置密钥'})[code]||'部分数据暂不可用';}
function renderWudao(){
 const w=state.wudao||wudaoSupplement;
 $('sectors').hidden=demo||!!replayDate;
 const panel=w?.featured;
 $('wudao-note').textContent=w?`${w.supplement?'接入后补充观察 · 不修改原阶段报告。 ':''}悟道 ${{OK:'采集成功',PARTIAL:'部分成功',UNAVAILABLE:'暂不可用'}[w.status]||'待确认'} · 行情 ${w.trade_date} · 题材快照 ${beijingTime(panel?.snapshot_time)}。原始强度不是百分制评分，题材之间成分可能重叠。${w.errors?.length?' 采集缺口：'+[...new Set(w.errors.map(wudaoError))].join('、'):''}`:'本阶段尚未接入悟道；下方为旧分类的规则评分。';
 $('wudao-rows').innerHTML=(panel?.rows||[]).map((r,i)=>`<tr><td><span class="rank-number ${i<3?'top':''}">${String(i+1).padStart(2,'0')}</span><span class="sector-name">${esc(r.themeName)}</span></td><td>${num(r.strength,0)}</td><td class="${color(r.pctChg)}">${pct(r.pctChg)}</td><td>${num(r.amount==null?null:r.amount/1e8)}</td><td>${num(r.mainNetAmount==null?null:r.mainNetAmount/1e8)}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">悟道热点暂不可用；未用旧榜冒充最新热点。</td></tr>';
 $('wudao-industry').innerHTML=(w?.industry?.rows||[]).map((r,i)=>`<tr><td>${i+1} · ${esc(r.themeName)}</td><td>${pct(r.pctChg)}</td><td>${num(r.mainNetAmount==null?null:r.mainNetAmount/1e8)}</td></tr>`).join('')||'<tr><td colspan="3" class="empty">无有效行业快照。</td></tr>';
}
function render(){
 renderWudao();
 renderEvidence();
 const m=state.market||{},q=state.data_quality||{};
 $('mode-link').href=demo||replayDate?'./':'?demo=1';$('mode-link').textContent=demo||replayDate?'返回正式工作台 ↗':'查看演示 ↗';
 $('mode-banner').hidden=!demo&&!replayDate&&!state.bootstrap_origin&&!state.weekend_review;
 $('mode-banner').textContent=replayDate?`${replayDate} 历史收盘复盘 · 使用当日收盘行情，含同日盘后接口补齐；使用事后行业分类。历史风险公告及盘前午盘快照未完整核验，非16:00时点回测。`:'DEMO / 演示模式 · 以下企业、事件、价格和评分均为模拟数据，不代表真实市场或投资建议。';
 if(!demo&&!replayDate&&state.bootstrap_origin)$('mode-banner').textContent='首次启动链 · 承接周末初始化快照；行情基准、事后行业分类和历史公告缺口见报告。本轮不计入常规因子效果统计。';
 if(!demo&&!replayDate&&state.weekend_review)$('mode-banner').textContent=`${state.date} 周末晚间二筛 · 沿用${state.quote_date}收盘行情并刷新公告；承接初始化候选，保留事后分类与历史风险缺口。`;
 $('date-label').textContent=state.date?state.date.replaceAll('-',' / '):loadError?'报告读取失败':'尚未运行';
 $('updated').textContent=state.finished_at||state.dashboard_updated_at?`最近完成 ${beijingTime(state.finished_at||state.dashboard_updated_at)}`:state.as_of_time?`报告截点 ${beijingTime(state.as_of_time)}`:loadError?'数据状态未知，请重试':'等待首份正式报告';
 $('next-stage').textContent=demo||replayDate?'历史 / 演示视图不预测下一次运行':state.next_scheduled_at?`下次调度 ${beijingTime(state.next_scheduled_at)}`:'交易日计划 08:00 / 12:00 / 22:00；调度可能延迟';
 $('stage-note').textContent=state.stage?`当前报告：${research.stageLabel(state.stage)} · 行情基准 ${state.quote_date||'未记录'} · 公告截点 ${beijingTime(state.event_cutoff_time||state.as_of_time)}。${research.oldStages.has(state.stage)?'上方为新三次流程；本报告保留原历史阶段与结果。':''}`:'每日三次研究流程；以正式任务与交易日历为准。';
 document.querySelectorAll('[data-stage]').forEach(el=>el.classList.toggle('current',el.dataset.stage===state.stage));
 $('environment').textContent=m.environment||'待确认';$('market-score').textContent=num(m.score,0);
 $('market-meter').style.width=`${Math.max(0,Math.min(100,m.score||0))}%`;
 $('market-basis').textContent=m.basis==='BREADTH_MVP'?'广度规则 · MVP':m.basis?String(m.basis):'无可靠评级';
 const factors=research.factorStatuses(state,marketEvidence,state.wudao||wudaoSupplement);
 $('market-note').textContent=state.quote_date?`行情基准 ${state.quote_date} · ${factors.filter(f=>f.status!=='AVAILABLE').length} 项指标需补齐或核验，详见能力表`:'数据不足时，不生成市场评级。';
 $('breadth').innerHTML=`${num(m.breadth==null?null:m.breadth*100,1)}<small>%</small>`;
 $('breadth-meter').style.width=`${Math.max(0,Math.min(100,(m.breadth||0)*100))}%`;
 $('breadth-note').textContent=`上涨 ${m.up??'—'} / 下跌 ${m.down??'—'}`;
 $('candidate-count').innerHTML=`${state.candidate_count??'—'}<small>只</small>`;
 $('candidate-note').textContent=`A ${state.pools?.POOL_A?.length||0} · B ${state.pools?.POOL_B?.length||0} · C ${state.pools?.POOL_C?.length||0}`;
 $('quality-value').textContent=q.status||'PENDING';$('quality-value').style.color=q.status==='RED'?'#bd6757':q.status==='GREEN'?'#648253':'#9b8e47';
 const dimensions=research.quality(state);
 $('quality-note').textContent=q.coverage==null?'等待真实数据校验':`行情 ${dimensions[0].value} · 板块映射 ${dimensions[1].value} · 候选计分 ${dimensions[3].value}`;
 $('quality-dimensions').innerHTML=dimensions.map(d=>`<div class="quality-dimension"><span>${esc(d.label)}</span><strong>${esc(d.value)}</strong><small>${esc(d.note)}</small></div>`).join('');
 $('position-counts').innerHTML=positions.map(p=>`<div><span><i></i>${p}</span><b>${state.position_counts?.[p]??'—'}</b></div>`).join('');
 $('sector-rows').innerHTML=(state.sectors||[]).slice(0,10).map((s,i)=>{
  const h=s.history||{},info=research.sectorPresentation(s);
  const entries=Object.entries(h).sort(([a],[b])=>a.localeCompare(b));
  const history=entries.map(([stage,score])=>`<span title="${esc(research.stageLabel(stage))}">${esc(stage.slice(0,2)+':'+stage.slice(2))} ${num(score,1)}${research.oldStages.has(stage)?'†':''}</span>`).join('');
  return `<tr><td><span class="rank-number ${i<3?'top':''}">${String(i+1).padStart(2,'0')}</span><span class="sector-name">${esc(s.name)}<small>${s.kind==='concept'?'概念':'行业'}</small></span></td><td><span class="inline-score">${num(s.score,1)}</span></td><td><div class="stage-history">${history||'未记录'}${entries.some(([stage])=>research.oldStages.has(stage))?'<small>† 历史阶段，保留原值</small>':''}</div></td><td>${num(s.breadth==null?null:s.breadth*100,1)}%</td><td>${info.valid??'—'} / ${info.total??'—'}<span class="second-line">${research.coverageText(info.coverage)}</span></td><td class="sector-basis">${pill(info.label)}<small>${esc(info.note)}</small></td></tr>`;
 }).join('')||'<tr><td colspan="6" class="empty">暂无可靠板块数据。</td></tr>';
 const previousSector=$('sector-filter').value;
 const options=[...new Set(Object.values(state.pools||{}).flat().map(s=>s.sector).filter(Boolean))];
 $('sector-filter').innerHTML='<option value="">全部板块</option>'+options.map(s=>`<option>${esc(s)}</option>`).join('');
 if(options.includes(previousSector))$('sector-filter').value=previousSector;
 for(const [i,k] of ['POOL_A','POOL_B','POOL_C'].entries())$(`count-${['a','b','c'][i]}`).textContent=state.pools?.[k]?.length||0;
 renderStocks();
 $('provenance').innerHTML=[['正式报告截点',beijingTime(state.as_of_time)],['公告观察截点',beijingTime(state.event_cutoff_time||state.as_of_time)],['行情基准日',state.quote_date],['补充核验完成',marketEvidence?.supplement?beijingTime(marketEvidence.finished_at):'无独立补充'],['采集完成',beijingTime(state.finished_at)],['Run ID',state.run_id?.slice(0,16)],['Google Docs',state.google_docs?.status||'NOT_CONFIGURED'],['AI增强',state.ai?.status||'DISABLED']].map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
 const sources={};for(const s of state.source_logs||[]){const old=sources[s.source_name]||{ok:0,total:0};old.total++;if(s.success)old.ok++;sources[s.source_name]=old;}
 $('source-list').innerHTML=Object.entries(sources).map(([k,v])=>`<div class="source-item"><span>${esc(k)}</span><span>${v.ok} / ${v.total} 成功</span></div>`).join('')||(demo?'<div class="source-item">SIMULATED · 仅用于功能验收</div>':'<div class="source-item">尚无采集记录</div>');
 renderFactorStatuses(factors);
 renderMarketContext();
 $('eliminations').innerHTML=(state.eliminations||[]).slice(0,100).map(s=>`<li>${esc(s.stock_code||s.code)} · ${esc(s.reason)}</li>`).join('')||'<li>暂无淘汰记录</li>';
 $('warnings').innerHTML=(state.warnings||[]).map(s=>`<li>${esc(s)}</li>`).join('');
 renderEvaluation();
 if(downloadURL)URL.revokeObjectURL(downloadURL);downloadURL=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:'application/json'}));$('download').href=downloadURL;
}
function renderFactorStatuses(factors){
 $('factor-count').textContent=`${factors.length} 项`;
 $('factor-statuses').innerHTML=factors.map(f=>`<details class="factor-item"><summary><h3>${esc(f.label)}</h3><span class="factor-status ${esc(f.status.toLowerCase())}">${esc(research.labels[f.status])}</span></summary><p>${esc(f.reason)}</p><dl><dt>覆盖</dt><dd>${esc(research.coverageText(f.coverage))}</dd><dt>评分使用</dt><dd>${f.used_in_score===true?'已计入':f.used_in_score===false?'未计入':'未记录'}</dd><dt>来源</dt><dd>${esc(Array.isArray(f.source)?f.source.join('、'):f.source||'未记录')}</dd><dt>数据时点</dt><dd>${esc(beijingTime(f.as_of_time))}</dd></dl></details>`).join('')||'<p class="evidence-copy">尚未收到因子能力报告。</p>';
}
function renderMarketContext(){
 const c=state.market_context;
 $('market-context').hidden=!c;
 if(!c)return;
 const fraction=v=>v==null?'—':num(v*100,1)+'%';
 const y=c.yesterday_limit_up||{},h=c.high_board_loss||{},a=c.market_amount||{};
 const cards=[['炸板率',fraction(c.break_rate),c.break_rate_basis||'暂无有效数据'],['昨日涨停名单溢价',pct(y.mean_return_pct),`跟踪 ${y.observed_count??0} / ${y.sample_count??0} 只 · 覆盖 ${fraction(y.coverage)}`],['昨日高位股下跌占比',fraction(h.negative_fraction),`至少3板 · 跟踪 ${h.observed_count??0} / ${h.sample_count??0} 只`]];
 $('context-cards').innerHTML=cards.map(([label,value,note])=>`<article><span>${esc(label)}</span><b>${esc(value)}</b><p>${esc(note)}</p></article>`).join('');
 $('context-date').textContent=`证据截点 ${beijingTime(c.as_of_time)} · 行情 ${c.trade_date||'未记录'} · 尚未计入市场规则分`;
 $('promotion-values').innerHTML=Object.entries(c.promotion||{}).map(([key,v])=>`<span>${esc(key.replace('_to_','进'))} <b>${v.status==='NO_SAMPLE'?'无样本':fraction(v.rate)}</b>（基数 ${v.base_count} 只）</span>`).join('');
 $('index-trends').innerHTML=(c.indices||[]).map(i=>`<tr><td>${esc(i.name)}<small class="second-line">${esc(i.trade_date)} · ${esc(i.source)}</small></td>${[5,10,20].map(n=>`<td>${pct(i['return_'+n+'d'])}<small class="second-line">${i['above_ma'+n]?'高于':'低于或等于'} MA${n}</small></td>`).join('')}</tr>`).join('')||'<tr><td colspan="4" class="empty">指数日线暂无有效结果。</td></tr>';
 $('amount-baseline').textContent=`全市场成交额：已有 ${a.history_days??0} / 20 个连续完整交易日基线；5 / 10 / 20 日倍数：${[5,10,20].map(n=>a['ratio_'+n+'d']==null?'待积累':num(a['ratio_'+n+'d'])+'倍').join(' / ')}。午间不与全日成交额比较。`;
}
function renderEvaluation(){
 const evals=research.evaluation(state);
 $('evaluation').innerHTML=demo?'<p class="validation-copy">演示结果不计入真实因子有效性统计。</p>':evals.length?evals.map(v=>`<article class="evaluation-item"><h3>${esc(research.stageLabel(v.key.split('/')[0]))} · ${esc(v.key.split('/').slice(1).join('/'))}</h3><div class="eval-row"><span>${v.sample_size} 条观察 · 独立交易日 ${v.independent_days??'未记录'}</span><strong>均值 ${pct(v.average_return)}</strong></div><p>观察窗口 ${esc(v.window_start||'未记录')} — ${esc(v.window_end||'未记录')}</p><p>${esc(v.definition)}</p>${v.legacy?'<p class="legacy-note">历史口径：观察条数不等于独立样本，不能直接跨阶段比较。</p>':''}</article>`).join(''):'<div class="eval-row"><span>真实样本</span><b>等待前瞻积累</b></div><p class="validation-copy">逐阶段记录观察窗口、独立交易日与收益定义。</p>';
}
function poolExplanation(pool){
 if(pool==='POOL_A'){
  const rows=state.pools?.POOL_A||[],first=rows.filter(r=>r.board_count===1).length,chain=rows.filter(r=>r.board_count>=2).length;
  return `${rows.length} 只候选：首板晋级观察 ${first} 只，已连板 ${chain} 只${rows.length-first-chain?`，板数待核验 ${rows.length-first-chain} 只`:''}。市场涨停记录还需通过入池规则；${research.oldStages.has(state.stage)?'当前显示历史阶段结果。':'22:00 完整扫描，08:00 与12:00继续验证。'}${!rows.length&&marketEvidence?.limit_pool?.length?` 已采集 ${marketEvidence.limit_pool.length} 条涨停记录，详见上方梯队。`:''}`;
 }
 if(pool==='POOL_C')return state.pool_notes?.[pool]||'独立催化需同时满足事实核验、价格与风险条件；未发现不等于没有事件。';
 const rows=state.pools?.POOL_B||[],missing=rows.filter(s=>s.amount_ratio_5d==null).length;
 return `趋势与位置规则观察，不代表实际可成交。${missing?`${missing} / ${rows.length} 只缺5日成交额比，启动 / 回调识别需结合该缺口。`:''}`;
}
function renderEvidence(){
 marketEvidence=MansonEvidence.select(state,evidenceSupplement,{demo,replay:!!replayDate});
 $('market-evidence').hidden=demo;
 $('evidence-update').hidden=!marketEvidence?.supplement;
 $('evidence-update').innerHTML=marketEvidence?.supplement?`已增加 ${esc(marketEvidence.trade_date)} 盘后补充核验 · ${esc(beijingTime(marketEvidence.finished_at))}。<a href="#market-evidence">查看涨停、连板及公告更新 →</a>`:'';
 $('evidence-content').hidden=!marketEvidence;
 $('evidence-empty').hidden=!!marketEvidence;
 $('evidence-empty').innerHTML=replayDate?'当前为历史复盘，后续采集不混入历史结果。<a href="./#market-evidence">打开最新正式工作台 →</a>':'本报告尚无可展示的涨停证据；未将空表解释为市场无涨停。';
 if(!marketEvidence)return;
 const rows=marketEvidence.limit_pool||[],chain=rows.filter(r=>r.board_count>=2),verified=(marketEvidence.events||[]).filter(e=>e.verified&&e.verification?.status==='VERIFIED_RULE');
 const known=rows.filter(r=>Number.isInteger(r.board_count)&&r.board_count>0);
 const max=known.length?Math.max(...known.map(r=>r.board_count)):null;
 $('evidence-note').textContent=`行情基准 ${marketEvidence.trade_date} · ${marketEvidence.supplement?'盘后补充采集':'正式任务记录'} · ${beijingTime(marketEvidence.observed_at)}。供应商板数与规则推导分别标注；市场涨停记录不等于 A 池策略候选。`;
 $('evidence-metrics').innerHTML=[['涨停记录',rows.length],['连板股（2板起）',chain.length],['供应商最高板',max==null?'—':max+'板'],['正文事实核验通过',verified.length]].map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');
 $('limit-ladder').innerHTML=MansonEvidence.ladder(rows).map(([n,group])=>`<button type="button" data-board="${esc(n)}"><b>${n==='1'?'首板':esc(n)+'板'}</b><span>${group.length} 只</span></button>`).join('');
 $('limit-board-filter').innerHTML='<option value="chain">只看连板（2板起）</option><option value="all">全部涨停记录</option>'+MansonEvidence.ladder(rows).map(([n,g])=>`<option value="${esc(n)}">${n==='1'?'首板':esc(n)+'板'} · ${g.length} 只</option>`).join('');
 document.querySelectorAll('[data-board]').forEach(b=>b.addEventListener('click',()=>{$('limit-board-filter').value=b.dataset.board;renderLimitRows();}));
 const reviewed=(marketEvidence.events||[]).filter(e=>e.verification);
 const reason={CONTRACT_NOT_CONFIRMED:'合同签署或生效条件未满足现有核验规则','NO_SUPPORTED_MATERIAL_FACT; NEEDS_REVIEW':'未提取到现有规则支持的明确量化事实',DOCUMENT_READ_FAILED:'正文读取失败',ISSUER_NOT_MATCHED:'正文证券代码未匹配'};
 $('evidence-events').innerHTML=reviewed.map(e=>`<article class="evidence-event"><div>${e.verified?pill('正文事实核验通过'):'<span class="pill orange">待进一步核验</span>'}<span>${esc(e.stock_code)}</span></div><h3><a href="${safeURL(e.document_url||e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a></h3><p>${esc(e.verification.evidence||reason[e.verification.reason]||e.verification.reason||'尚无明确正文证据')}</p>${e.verification.score_basis?`<p>${esc(e.verification.score_basis)}</p>`:''}<small>公告 ${esc(e.publish_time_precision==='date'?e.publish_time.slice(0,10)+'（仅日期）':beijingTime(e.publish_time))} · 核验 ${esc(beijingTime(e.verification.observed_at))}</small></article>`).join('')||'<p class="empty">暂无完成正文核验的公告；不按标题补足 C 池。</p>';
 const ce=marketEvidence.catalyst_evidence||{};
 $('event-evidence-note').textContent=`限定扫描发现 ${ce.discovered??'—'} 条，正文读取 ${ce.documents_read??'—'} 份。核验事实仍需通过其余筛选，才进入 C 池。${marketEvidence.supplement?'本补充未改写原正式报告或原 Google Docs。':''}`;
 renderLimitRows();
}
function sealTime(value){const s=String(value??'').padStart(6,'0');return /^\d{6}$/.test(s)&&value!=null?`${s.slice(0,2)}:${s.slice(2,4)}:${s.slice(4,6)}`:'—';}
function renderLimitRows(){
 const f=$('limit-board-filter').value,query=$('limit-search').value.trim();
 const rows=(marketEvidence?.limit_pool||[]).filter(r=>(f==='all'||f==='chain'&&r.board_count>=2||String(r.board_count??'未知')===f)&&(!query||(r.name||'').includes(query)||r.code.includes(query))).sort((a,b)=>(b.board_count||0)-(a.board_count||0)||String(a.code).localeCompare(String(b.code)));
 $('limit-shown').textContent=`显示 ${rows.length} / ${marketEvidence?.limit_pool?.length||0} 条`;
 $('limit-rows').innerHTML=rows.map(r=>`<tr><td><strong>${esc(r.name||r.code)}</strong><span class="second-line">${esc(r.code)}</span></td><td>${r.board_count==null?'供应商未知':esc(r.board_count)+'板'}${r.derived_board_count?`<span class="second-line">规则推导 ${esc(r.derived_board_count)}板</span>`:''}</td><td>${num(r.limit_up_price)}</td><td>${sealTime(r.first_seal)}</td><td>${sealTime(r.last_seal)}</td><td>${r.break_count==null?'—':esc(r.break_count)}</td><td>${num(r.seal_amount==null?null:r.seal_amount/1e8)}</td><td>${esc(r.source==='eastmoney'?'东方财富':r.source)}${r.identity_basis==='rule_derived_not_vendor_confirmed'?'<span class="second-line">规则推导，待核验</span>':''}</td></tr>`).join('')||'<tr><td colspan="8" class="empty">当前条件下无记录。</td></tr>';
}
function renderStocks(){
 const bf=activePool==='POOL_A'?$('candidate-board-filter').value:'';
 $('candidate-board-filter').closest('label').hidden=activePool!=='POOL_A';
 const group=(state.pools?.[activePool]||[]).filter(s=>(!$('sector-filter').value||s.sector===$('sector-filter').value)&&(!$('position-filter').value||s.position_type===$('position-filter').value)&&(!$('risk-filter').value||(s.technical_risk||s.risk)===$('risk-filter').value)&&(!bf||bf==='first'&&s.board_count===1||bf==='chain'&&s.board_count>=2)).sort((a,b)=>(b[$('sort').value]??-1)-(a[$('sort').value]??-1));
 $('shown-count').textContent=`${group.length} / ${state.pools?.[activePool]?.length||0} 只候选`;
 $('pool-note').hidden=!poolExplanation(activePool);$('pool-note').textContent=poolExplanation(activePool);
 const diagnostics=activePool==='POOL_C'?research.catalystDiagnostics(state,marketEvidence):[];
 $('catalyst-diagnostics').hidden=!diagnostics.length;
 $('catalyst-diagnostics').innerHTML=diagnostics.map(d=>`<article class="catalyst-diagnostic"><strong>${esc(d.name)} ${esc(d.code)} · ${d.passed?'已通过入池条件':'未入选原因'}</strong><ul>${(d.reasons.length?d.reasons:['未记录具体条件']).map(r=>`<li>${esc(r)}</li>`).join('')}</ul></article>`).join('');
 $('stock-rows').innerHTML=group.map(s=>`<tr><td><button class="stock-name" data-code="${esc(s.stock_code)}">${esc(s.stock_name)}<small>${esc(s.stock_code)} · 查看详情 ↗</small></button>${research.boardLabel(s)?`<span class="second-line board-label">${esc(research.boardLabel(s))}</span>`:''}</td><td>${esc(s.sector)}<span class="second-line">板块分 ${num(s.sector_score,1)}</span></td><td>${num(s.price)}<span class="second-line ${color(s.change_pct)}">${pct(s.change_pct)}</span></td><td>${pill(s.position_type)}<span class="second-line">技术风险：${esc(s.technical_risk||s.risk||'未知')}</span></td><td><strong class="stock-score">${num(s.total_score,1)}</strong><span class="second-line coverage-label">计分覆盖 ${esc(research.coverageText(s.score_coverage))}</span></td><td class="candidate-reason">${esc(research.eligibility(s)[0])}<span class="second-line review-label">${esc(research.eventReview(s))}</span></td></tr>`).join('')||`<tr><td colspan="6" class="empty">${(state.pools?.[activePool]?.length)?'当前筛选条件下没有候选。':loadError?'报告读取失败，候选状态未知。':state.status==='NOT_STARTED'?'尚未收到首份正式报告。':'本池暂无已确认候选，详见上方说明。'}</td></tr>`;
 document.querySelectorAll('[data-code]').forEach(b=>b.addEventListener('click',()=>showDetail(b.dataset.code)));
}
function chart(bars){
 const data=(bars||[]).filter(b=>[b.open,b.high,b.low,b.close].every(Number.isFinite)).slice(-45);
 if(!data.length)return '<p>暂无可靠K线历史。</p>';
 const w=730,h=190,left=40,top=15,min=Math.min(...data.map(x=>x.low)),max=Math.max(...data.map(x=>x.high)),range=max-min||1;
 const y=v=>top+(max-v)/range*(h-45),step=(w-left-16)/data.length;
 let svg=`<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="最近45根未经复权的日线蜡烛图；午盘最后一根为半日数据">`;
 for(let i=0;i<4;i++){const value=min+range*i/3;svg+=`<line x1="40" x2="720" y1="${y(value)}" y2="${y(value)}" stroke="#e5ebdc"/><text x="3" y="${y(value)+4}" fill="#8b9b7e" font-size="9">${num(value,1)}</text>`;}
 data.forEach((b,i)=>{const x=left+i*step+step/2,c=b.close>=b.open?'#c77d68':'#709a79';svg+=`<line x1="${x}" x2="${x}" y1="${y(b.high)}" y2="${y(b.low)}" stroke="${c}"/><rect x="${x-step*.29}" y="${y(Math.max(b.open,b.close))}" width="${step*.58}" height="${Math.max(1,Math.abs(y(b.open)-y(b.close)))}" fill="${c}"/>`;});
 svg+=`<text x="40" y="185" fill="#8b9b7e" font-size="9">${esc(data[0].timestamp.slice(0,10))}</text><text x="650" y="185" fill="#8b9b7e" font-size="9">${esc(data.at(-1).timestamp.slice(0,10))}</text></svg>`;return svg;
}
function safeURL(value){try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)?esc(u.href):'#';}catch{return '#';}}
function showDetail(code){
 const s=Object.values(state.pools||{}).flat().find(x=>x.stock_code===code);if(!s)return;
 const fields=[['现价',s.price],['MA5',s.ma5],['MA10',s.ma10],['MA20',s.ma20],['MA60',s.ma60],['ATR14',s.atr],['NATR %',s.natr],['MoveATR',s.move_atr],['供应商板数',s.board_count],['日线推导板数',s.derived_board_count],['板块分',s.sector_score],['计分覆盖 %',s.score_coverage==null?null:s.score_coverage*100],['量比',s.volume_ratio],['换手率 %',s.turnover]];
 $('detail-body').innerHTML=`<h2>${esc(s.stock_name)} <small>${esc(code)}</small></h2><p>${esc(s.sector)} · ${esc(s.position_type)} · ${esc(s.atr_state)} ATR · 技术风险：${esc(s.risk)} · ${esc(research.eventReview(s))}<br>行情时间 ${esc(s.timestamp)} · 来源 ${esc(s.source)} · 价格序列未经复权</p><div class="detail-grid">${fields.map(([k,v])=>`<div>${esc(k)}<b>${num(v)}</b></div>`).join('')}</div>${chart(s.bars)}<h3 class="detail-heading">多日价格与成交额</h3><div class="table-wrap"><table><thead><tr><th>窗口</th><th>涨跌幅</th><th>前 N 日均成交额（亿）</th><th>当日 / 前 N 日均值</th></tr></thead><tbody>${[5,10,20].map(n=>`<tr><td>${n} 日</td><td>${pct(s['return_'+n+'d'])}</td><td>${num(s['amount_mean_'+n+'d']==null?null:s['amount_mean_'+n+'d']/1e8)}</td><td>${s['amount_ratio_'+n+'d']==null?'缺少可比数据':num(s['amount_ratio_'+n+'d'])+' 倍'}</td></tr>`).join('')}</tbody></table></div><p class="detail-note">成交额均值不含当前交易日；午间缺少同时间基线时不计算倍数。计分覆盖 ${esc(research.coverageText(s.score_coverage))}，缺失权重会重新归一，规则分不能当作成功概率。</p><div class="detail-columns"><div><h3 class="detail-heading">最关键正因子</h3><p>${esc(s.positive_factor)}</p><h3 class="detail-heading">验证条件</h3><p>${esc(research.formatCondition(s.validation_condition))}</p></div><div><h3 class="detail-heading">最关键负因子</h3><p>${esc(s.negative_factor)}</p><h3 class="detail-heading">失效条件</h3><p>${esc(research.formatCondition(s.invalidation_condition))}</p></div></div><p>涨停身份：${esc(({vendor_limit_price:'供应商明确价格证据',rule_derived_not_vendor_confirmed:'价格规则推导，待交叉核验'})[s.limit_identity_basis]||'未记录')}；供应商板数与日线推导分别展示，推导未覆盖全部特殊交易及除权情形。</p><p>量价：${esc(s.volume_type)}。主观上涨/连板概率：${s.subjective_probability==null?'未输出（无已校准模型）':`${num(s.subjective_probability*100,0)}%（AI未校准）`}。${esc(research.tradability(s).label)}：${esc(research.tradability(s).reason)}</p><h3 class="detail-heading">事件与催化</h3>${(s.events||[]).map(e=>`<div class="event"><a href="${safeURL(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a><br><small>${esc(e.source)} · ${esc(e.publish_time_precision==='date'?e.publish_time.slice(0,10)+'（仅日期，无精确发布时间）':e.publish_time)} · ${esc(e.expectation||'证据不足')} · ${e.verified?'已核验':'待正文核验'}</small>${e.verification?`<p>${e.verified?'正文量化事实核验通过':'正文证据尚未满足核验要求'}<br>${esc(e.verification.evidence||'')}<br>${esc(e.verification.score_basis||'')}</p>`:''}</div>`).join('')||'<p>无已确认事件；不按新闻条数加分。</p>'}<h3 class="detail-heading">历史排名</h3><p>${(s.rank_history||[]).map(r=>`${esc(r.date)} ${esc(r.stage)} #${r.rank}（${num(r.score)}）`).join(' → ')||'首次观察，等待后续验证。'}</p>`;
 $('detail').showModal();
}
document.querySelectorAll('[data-pool]').forEach(b=>b.addEventListener('click',()=>{activePool=b.dataset.pool;document.querySelectorAll('[data-pool]').forEach(x=>x.setAttribute('aria-selected',String(x===b)));renderStocks();}));
for(const id of ['sector-filter','position-filter','risk-filter','candidate-board-filter','sort'])$(id).addEventListener('change',renderStocks);
$('limit-board-filter').addEventListener('change',renderLimitRows);
$('limit-search').addEventListener('input',renderLimitRows);
$('refresh').addEventListener('click',load);$('close-detail').addEventListener('click',()=>$('detail').close());
$('detail').addEventListener('click',e=>{if(e.target===$('detail')){const r=$('detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('detail').close();}});
function activateNavigation(id){
 document.querySelectorAll('.sidebar nav a').forEach(a=>{const active=a.hash==='#'+id;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');});
}
function syncNavigation(){
 const ids=['overview','market-evidence','sectors','candidates','quality'];
 const top=innerWidth<=760?150:80;
 const visible=ids.map(id=>$(id)).filter(el=>el&&!el.hidden&&el.getBoundingClientRect().top<=top);
 const id=visible.at(-1)?.id||'overview';activateNavigation(id);
}
let scrollPending=false;
addEventListener('scroll',()=>{if(!scrollPending){scrollPending=true;requestAnimationFrame(()=>{syncNavigation();scrollPending=false;});}},{passive:true});
addEventListener('hashchange',()=>activateNavigation(location.hash.slice(1)||'overview'));
document.querySelectorAll('.sidebar nav a').forEach(a=>a.addEventListener('click',()=>activateNavigation(a.hash.slice(1))));
activateNavigation(location.hash.slice(1)||'overview');
load();
