'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,n=2)=>v==null||!Number.isFinite(Number(v))?'—':Number(v).toFixed(n);
const pct=v=>v==null?'—':`${Number(v)>0?'+':''}${num(v)}%`;
const color=v=>Number(v)>0?'positive':Number(v)<0?'negative':'';
const time=v=>v&&Number.isFinite(Date.parse(v))?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(v)):'未记录';
const safeURL=v=>{try{const u=new URL(v);return ['http:','https:'].includes(u.protocol)?esc(u.href):'#';}catch{return '#';}};
const params=new URLSearchParams(location.search),demo=params.get('demo')==='1';
const replay=!demo&&/^\d{4}-\d{2}-\d{2}$/.test(params.get('replay')||'')?params.get('replay'):null;
const focus=MansonFocus,research=MansonResearch;
let state={},reviews=null,active='all',downloadURL;
async function optional(path){try{const r=await fetch(path,{cache:'no-store'});return r.ok?await r.json():null;}catch{return null;}}
async function load(){
 $('refresh').disabled=true;reviews=null;$('run-banner').hidden=true;
 try{
  const response=await fetch(`data/${demo?'demo':replay?`replays/${replay}`:'latest'}.json`,{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  state=await response.json();
  if(!state.pools||!demo&&state.mode==='demo'||replay&&(state.mode!=='retrospective'||state.date!==replay)||!replay&&!demo&&state.mode==='retrospective')throw new Error('报告模式不匹配');
  if(!demo&&!replay){
   const [extra,docs,status]=await Promise.all([optional('data/research_overlay.json'),optional('data/catalyst_reviews.json'),optional('data/run_status.json')]);
   state=focus.overlay(state,extra);reviews=docs;
   if(status&&status.status!=='COMPLETE'){$('run-banner').hidden=false;$('run-banner').textContent=`最近任务：${status.date} ${research.stageLabel(status.stage)} · ${status.status}。${(status.warnings||[]).join(' ')}`;}
  }
  render();
 }catch(e){
  state={pools:{},data_quality:{},status:'LOAD_FAILED'};render();
  $('run-banner').hidden=false;$('run-banner').textContent=`报告读取失败（${e.message}）。请刷新重试；读取失败不表示没有候选。`;
 }
 $('refresh').disabled=false;
}
function render(){
 const rows=focus.items(state),s=state.stock_research||{},m=state.market||{},q=state.data_quality||{};
 $('date-label').textContent=state.quote_date?`${state.quote_date} 行情`:'等待有效报告';
 $('updated').textContent=`${s.generated_at?'分析生成':'报告完成'} ${time(s.generated_at||state.finished_at)}`;
 $('next-stage').textContent=demo||replay?'历史视图':state.next_scheduled_at?`下次计划 ${time(state.next_scheduled_at)}`:'交易日 08:00 / 12:00 / 22:00';
 $('mode-link').href=demo||replay?'./':'?demo=1';$('mode-link').textContent=demo||replay?'返回正式工作台':'查看演示';
 const banner=demo?'演示模式：企业、行情和事件为模拟数据。':replay?`${replay} 历史收盘复盘；保留当时结果，不倒填本版入场计划。`:state.projection?.note||'';
 $('mode-banner').hidden=!banner;$('mode-banner').textContent=banner;
 $('market-context').textContent=`市场背景 ${m.environment||'待确认'} · 上涨占比 ${num(m.breadth==null?null:m.breadth*100,1)}% · 仅作个股研究背景`;
 for(const kind of ['momentum','catalyst','volatile'])$(`count-${kind}`).textContent=rows.filter(r=>focus.matches(r,kind)).length;
 const f=s.coverage||state.funnel||{};
 $('scope-note').textContent=`${rows.length} 只跟踪 · 历史样本 ${f.factor_ready??q.history_ready_count??'—'} / 行情 ${f.valid_quotes??state.stock_count??'—'}`;
 renderStocks();renderReviews();renderChanges();
 $('analysis-note').textContent=s.note||'此报告尚未生成本版个股分析；历史结果仅按原始字段展示。';
 const dims=research.quality(state);
 $('quality-dimensions').innerHTML=dims.map(d=>`<div><span>${esc(d.label)}</span><strong>${esc(d.value)}</strong><small>${esc(d.note)}</small></div>`).join('');
 $('provenance').innerHTML=[['行情日期',state.quote_date],['原任务阶段',research.stageLabel(state.stage)],['原报告截点',time(state.as_of_time)],['公告观察截点',time(state.event_cutoff_time)],['本版分析生成',time(s.generated_at)],['语言模型分析',state.ai?.status==='COMPLETE'?'见对应记录':'未启用；自动卡片为证据规则分析'],['悟道调用',state.wudao?.status||'本快照未记录'],['Google Docs',state.google_docs?.status||'未记录']].map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
 const sources={};for(const x of state.source_logs||[]){sources[x.source_name]??={ok:0,total:0};sources[x.source_name].total++;if(x.success)sources[x.source_name].ok++;}
 $('source-list').innerHTML=Object.entries(sources).map(([k,v])=>`<div class="source-row"><span>${esc(k)}</span><span>${v.ok}/${v.total} 次成功</span></div>`).join('');
 $('warnings').innerHTML=(state.warnings||[]).map(w=>`<li>${esc(w)}</li>`).join('');
 $('factor-statuses').innerHTML=research.factorStatuses(state).map(f=>`<div class="factor-row"><strong>${esc(f.label)}</strong><span>${esc(research.labels[f.status])}</span><p>${esc(f.reason)}</p></div>`).join('');
 if(downloadURL)URL.revokeObjectURL(downloadURL);downloadURL=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:'application/json'}));$('download').href=downloadURL;
}
function planHTML(p,compact=false){
 const zone=p.entry_zone;
 return `<div class="price-plan ${zone?'':'observation'}"><div class="plan-title">${esc(p.label)}</div><div class="plan-values"><div><small>${zone?'条件观察区间':'入场价格'}</small><strong>${zone?`${num(zone[0])}–${num(zone[1])}`:'暂不提供'}</strong></div><div><small>失效参考</small><b>${p.invalidation_price?num(p.invalidation_price):'—'}</b></div>${!compact?`<div><small>20日高点参考</small><b>${num(p.resistance_reference)}</b></div>`:''}</div><p>${esc(p.trigger)}</p></div>`;
}
function renderStocks(){
 const all=focus.items(state),sort=$('sort').value;
 const rows=all.filter(s=>focus.matches(s,active,$('search').value)).sort((a,b)=>sort==='stock_code'?a.stock_code.localeCompare(b.stock_code):active==='all'&&sort==='research_priority'?(a.pool==='POOL_H')-(b.pool==='POOL_H')||(b[sort]??b.total_score??-1)-(a[sort]??a.total_score??-1):(b[sort]??b.total_score??-1)-(a[sort]??a.total_score??-1));
 const note=active==='volatile'?'高波动是风险与弹性特征，不是“将成为妖股”的预测；默认不提供追涨买点。':active==='catalyst'?'仅显示满足独立催化条件的个股。正文实读与尚待兑现的线索，见下方催化研判。':'区间来自对应日期的日线结构；到价仍需承接确认，遇新报告或公司行动需重算。';
 $('list-note').textContent=`显示 ${rows.length} 只 · ${note}`;
 $('stock-cards').innerHTML=rows.map(s=>{
  const r=s.research||focus.legacy(s),p=r.price_plan;
  return `<article class="stock-card ${s.pool==='POOL_H'?'volatile':''}"><div class="stock-head"><div><span class="category">${esc(focus.groups[s.pool])}${s.independent_catalyst&&s.pool!=='POOL_C'?' · 独立催化':''}</span><h3><button class="stock-name" data-code="${esc(s.stock_code)}">${esc(s.stock_name)}</button><small>${esc(s.stock_code)}</small></h3><span class="sector">${esc(s.sector||'归属待确认')}${s.wudao_themes?.length?' · '+esc(s.wudao_themes.slice(0,2).join(' / ')):''}</span></div><span class="change-tag">${esc(r.change?.label||'研究观察')}</span></div><div class="stock-metrics"><div><small>快照价</small><strong>${num(s.price)}</strong></div><div><small>5日</small><b class="${color(s.return_5d)}">${pct(s.return_5d)}</b></div><div><small>20日</small><b class="${color(s.return_20d)}">${pct(s.return_20d)}</b></div></div><h4>${esc(r.headline)}</h4><p class="thesis">${esc(r.conclusion)}</p>${planHTML(p,true)}<div class="catalyst-line"><span>催化</span><p>${esc(r.catalyst.headline)}</p></div><div class="card-footer"><small>行情 ${time(s.timestamp)} · 规则分析</small><button class="detail-button" data-code="${esc(s.stock_code)}">研究详情 ↗</button></div></article>`;
 }).join('')||`<div class="empty"><h3>${$('search').value?'没有匹配的个股':active==='catalyst'?'暂无已确认的独立催化个股':'当前没有符合条件的跟踪个股'}</h3><p>${state.status==='LOAD_FAILED'?'数据读取失败，请重试。':active==='catalyst'?'不为凑数量把标题当利好。下方实读分析解释了每条线索的业务影响与兑现前提。':'缺数据或条件不满足时保留空结果。'}</p>${active==='catalyst'?'<a href="#catalysts">查看催化研判 ↓</a>':''}</div>`;
 $('stock-cards').querySelectorAll('[data-code]').forEach(b=>b.addEventListener('click',()=>showDetail(b.dataset.code)));
}
function sourceHTML(sources){return `<details class="evidence"><summary>查看原文依据与时间</summary>${sources.map(s=>`<p><a href="${safeURL(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title||'原始资料')} ↗</a><small>公告 ${esc(s.publish_time_precision==='date'?s.published_at?.slice(0,10)+'（仅日期）':s.published_at||'未记录')}${s.read_at?' · 阅读 '+time(s.read_at):''}</small></p>`).join('')}</details>`;}
function reviewCard(r,manual){
 return `<article class="review-card ${r.stance==='风险'||r.status==='RISK'?'risk-review':''}"><div class="review-top"><span>${esc(r.stock_name||r.stock_code)} <small>${esc(r.stock_code)}</small></span><span class="pill">${manual?'逐份实读':r.status==='RISK'?'风险':'规则研判'}${r.stance?' · '+esc(r.stance):''}</span></div><h3>${esc(r.headline)}</h3><p>${esc(r.conclusion)}</p>${r.business_impact?`<div class="impact"><b>如何影响业务</b><p>${esc(r.business_impact)}</p></div>`:''}<div class="next-check"><b>接下来验证</b><p>${esc(Array.isArray(r.next_check)?r.next_check.join(' '):r.next_check)}</p></div>${r.independent_catalyst_assessment?`<p class="assessment">${esc(r.independent_catalyst_assessment)}</p>`:''}${sourceHTML(r.sources||[])}</article>`;
}
function renderReviews(){
 const current=state.stock_research?.catalyst_reviews||[];
 const validManual=!demo&&!replay&&reviews?.analyst_basis==='DOCUMENT_REVIEW'&&Number.isFinite(Date.parse(reviews.generated_at))&&Date.parse(reviews.generated_at)<=Date.now();
 const same=validManual&&reviews.source_snapshot_run_id===state.run_id;
 const manual=same?reviews.items||[]:[];
 const covered=new Set(manual.map(r=>r.stock_code));
 $('catalyst-note').textContent=same?`以下分析于 ${time(reviews.generated_at)} 逐份阅读官方正文后补充，区别于原任务当时的核验结果；相同项目的连续进展合并分析。`:'自动分析只解释已保存的证据与经营条件；未核验的标题不作为买入理由。';
 $('catalyst-cards').innerHTML=manual.map(r=>reviewCard(r,true)).join('')+current.filter(r=>!covered.has(r.stock_code)).map(r=>reviewCard(r,false)).join('')||'<p class="section-copy">本阶段没有足够的正文证据形成独立催化分析。</p>';
 if(validManual&&!same)$('catalyst-cards').insertAdjacentHTML('beforeend',`<details class="past-reviews"><summary>历史实读分析 · ${esc(reviews.source_snapshot_date)}（不代表当前催化）</summary>${reviews.items.map(r=>reviewCard(r,true)).join('')}</details>`);
}
function renderChanges(){
 const rows=focus.items(state).filter(s=>s.research?.change?.previous_run_id);
 $('tracking-changes').innerHTML=rows.map(s=>`<div class="tracking-row"><b>${esc(s.stock_name)} <small>${esc(s.stock_code)}</small></b><span>${esc(s.research.change.label)}</span><span>较前次快照 ${pct(s.research.change.price_change_pct)}</span></div>`).join('')+(state.transitions||[]).map(s=>`<div class="tracking-row"><b>${esc(s.stock_name||s.stock_code)}</b><span>${esc(s.transition)}</span><span>${esc(s.reason)}</span></div>`).join('')||'<p class="section-copy">本版首次建立个股跟踪。下一次正式阶段会记录延续、暂停及前次条件是否失效；不把历史补算当成当时已发出的信号。</p>';
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
function showDetail(code){
 const s=focus.items(state).find(s=>s.stock_code===code);if(!s)return;
 const r=s.research||focus.legacy(s),p=r.price_plan;
 const sources=(s.events||[]).map(e=>({url:e.document_url||e.url,title:e.title,published_at:e.publish_time,publish_time_precision:e.publish_time_precision}));
 $('detail-body').innerHTML=`<div class="detail-intro"><span class="category">${esc(focus.groups[s.pool])}</span><h2>${esc(s.stock_name)} <small>${esc(code)}</small></h2><p>行情 ${esc(s.timestamp)} · ${esc(s.source)} · 未复权价格</p></div><h3>${esc(r.headline)}</h3><p>${esc(r.conclusion)}</p>${planHTML(p)}${p.reward_risk_to_resistance!=null?`<p class="detail-note">至20日高点的空间 / 失效距离：${num(p.reward_risk_to_resistance)}；按观察区上沿测算。前高只作阻力参考，不是目标收益。</p>`:''}<p class="detail-note">${esc(p.valid_until||'历史报告无有效入场计划')}</p><ul>${(p.no_trade||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>${chart(s.bars)}<div class="detail-metrics">${[['MA5',s.ma5],['MA10',s.ma10],['MA20',s.ma20],['ATR14',s.atr]].map(([k,v])=>`<div><small>${k}</small><strong>${num(v)}</strong></div>`).join('')}</div><h3>催化如何改变判断</h3><h4>${esc(r.catalyst.headline)}</h4><p>${esc(r.catalyst.conclusion)}</p><p><b>下一步：</b>${esc(r.catalyst.next_check||'核对事件原始依据。')}</p><h3>研究边界</h3><ul>${(r.limitations||['旧报告未保存本版分析。']).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>${sourceHTML(sources)}<details><summary>量价指标明细</summary><div class="table-wrap"><table><thead><tr><th>窗口</th><th>涨跌幅</th><th>前N日成交额均值</th><th>当日/均值</th></tr></thead><tbody>${[5,10,20].map(n=>`<tr><td>${n}日</td><td>${pct(s['return_'+n+'d'])}</td><td>${num(s['amount_mean_'+n+'d']==null?null:s['amount_mean_'+n+'d']/1e8)}亿</td><td>${num(s['amount_ratio_'+n+'d'])}</td></tr>`).join('')}</tbody></table></div><p>成交额均值不含当前日；午间缺同时间基线则不计算。优先顺序用于研究排序，不能理解为成功概率。</p></details>`;
 $('detail').showModal();
}
function setKind(kind){active=kind;document.querySelectorAll('.tabs [data-kind]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.kind===kind)));renderStocks();}
document.querySelectorAll('[data-kind]').forEach(b=>b.addEventListener('click',()=>{setKind(b.dataset.kind);if(b.classList.contains('summary-card'))$('candidates').scrollIntoView({behavior:'smooth',block:'start'});}));
$('search').addEventListener('input',renderStocks);$('sort').addEventListener('change',renderStocks);$('refresh').addEventListener('click',load);$('close-detail').addEventListener('click',()=>$('detail').close());
$('detail').addEventListener('click',e=>{if(e.target===$('detail')){const r=$('detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('detail').close();}});
function syncNav(){const ids=['overview','catalysts','changes','quality'];const id=ids.filter(x=>$(x).getBoundingClientRect().top<180).at(-1)||'overview';document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.hash==='#'+id));}
addEventListener('scroll',syncNav,{passive:true});
if(['#market-evidence','#evidence-announcements'].includes(location.hash))location.hash='catalysts';
if(['#sectors','#rule-sectors'].includes(location.hash))location.hash='overview';
load();
