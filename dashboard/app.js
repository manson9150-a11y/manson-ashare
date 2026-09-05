'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (value, digits=2) => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(digits);
const pct = value => value == null ? '—' : `${Number(value)>0?'+':''}${num(value)}%`;
const color = value => Number(value)>0?'positive':Number(value)<0?'negative':'';
const positions=['启动观察','趋势观察','高位观察','回调观察','排除'];
const demo=new URLSearchParams(location.search).get('demo')==='1';
let state={},activePool='POOL_A',downloadURL;
function pill(label){return `<span class="pill ${/高位|高|极端|退潮|转弱/.test(label)?'red':/启动|中|警告/.test(label)?'orange':''}">${esc(label)}</span>`;}
async function load(){
 $('refresh').disabled=true;
 try{
  const response=await fetch(`data/${demo?'demo':'latest'}.json`,{cache:'no-store'});
  if(!response.ok)throw new Error('EMPTY');
  state=await response.json();
  if(!demo && state.mode==='demo')throw new Error('DEMO_IN_PRODUCTION');
 }catch(error){
  state={mode:'live',status:'NOT_STARTED',pools:{POOL_A:[],POOL_B:[],POOL_C:[]},market:{},sectors:[],data_quality:{status:'PENDING'},warnings:['尚未收到正式云端报告。请先把仓库连接 GitHub Actions；演示入口仅展示模拟数据。']};
 }
 render();
 if(!demo){try{const r=await fetch('data/run_status.json',{cache:'no-store'});if(r.ok){const s=await r.json();if(s.status!=='COMPLETE'){$('run-banner').hidden=false;$('run-banner').textContent=`最近任务：${s.date} ${s.stage} · ${s.status}。${(s.warnings||[]).join(' ')}`;}}}catch{}}
 $('refresh').disabled=false;
}
function render(){
 const m=state.market||{},q=state.data_quality||{};
 $('mode-link').href=demo?'./':'?demo=1';$('mode-link').textContent=demo?'返回正式工作台 ↗':'查看演示 ↗';
 $('mode-banner').hidden=!demo;
 $('mode-banner').textContent='DEMO / 演示模式 · 以下企业、事件、价格和评分均为模拟数据，不代表真实市场或投资建议。';
 $('date-label').textContent=state.date?state.date.replaceAll('-',' / '):'等待正式行情';
 $('updated').textContent=state.as_of_time?`研究截点 ${state.as_of_time.slice(11,16)} · 北京时间`:'首次交易日收盘扫描后更新';
 document.querySelectorAll('[data-stage]').forEach(el=>el.classList.toggle('current',el.dataset.stage===state.stage));
 $('environment').textContent=m.environment||'待确认';$('market-score').textContent=num(m.score,0);
 $('market-meter').style.width=`${Math.max(0,Math.min(100,m.score||0))}%`;
 $('market-basis').textContent=m.basis==='BREADTH_MVP'?'广度规则 · MVP':'无可靠评级';
 $('market-note').textContent=state.quote_date?`行情基准 ${state.quote_date} · ${m.missing_factors?.length||0} 项增强指标待接入`:'数据不足时，不生成市场评级。';
 $('breadth').innerHTML=`${num(m.breadth==null?null:m.breadth*100,1)}<small>%</small>`;
 $('breadth-meter').style.width=`${Math.max(0,Math.min(100,(m.breadth||0)*100))}%`;
 $('breadth-note').textContent=`上涨 ${m.up??'—'} / 下跌 ${m.down??'—'}`;
 $('candidate-count').innerHTML=`${state.candidate_count??'—'}<small>只</small>`;
 $('candidate-note').textContent=`A ${state.pools?.POOL_A?.length||0} · B ${state.pools?.POOL_B?.length||0} · C ${state.pools?.POOL_C?.length||0}`;
 $('quality-value').textContent=q.status||'PENDING';$('quality-value').style.color=q.status==='RED'?'#bd6757':q.status==='GREEN'?'#648253':'#9b8e47';
 $('quality-note').textContent=q.coverage==null?'等待真实数据校验':`行情覆盖 ${num(q.coverage*100,1)}% · 因子缺口明确留空`;
 $('position-counts').innerHTML=positions.map(p=>`<div><span><i></i>${p}</span><b>${state.position_counts?.[p]??'—'}</b></div>`).join('');
 $('sector-rows').innerHTML=(state.sectors||[]).slice(0,10).map((s,i)=>{const h=s.history||{},v=Object.entries(h).sort(([a],[b])=>a.localeCompare(b)).map(([,x])=>x);const arrow=v.length<2?'—':v.at(-1)>v.at(-2)?'↗':v.at(-1)<v.at(-2)?'↘':'→';return `<tr><td><span class="rank-number ${i<3?'top':''}">${String(i+1).padStart(2,'0')}</span><span class="sector-name">${esc(s.name)}<small>${s.kind==='concept'?'概念':'行业'}</small></span></td><td><span class="inline-score">${num(s.score,0)}<span class="inline-track"><i style="width:${Math.max(0,Math.min(100,s.score||0))}%"></i></span>${arrow}</span></td><td>${num(h['0830'],0)}</td><td>${num(h['1135'],0)}</td><td>${num(h['1600'],0)}</td><td>${num(s.breadth*100,0)}%</td><td>${pill(s.state)}</td></tr>`;}).join('')||'<tr><td colspan="7" class="empty">暂无可靠板块数据。首次收盘扫描后展示。</td></tr>';
 const options=[...new Set(Object.values(state.pools||{}).flat().map(s=>s.sector))];
 $('sector-filter').innerHTML='<option value="">全部板块</option>'+options.map(s=>`<option>${esc(s)}</option>`).join('');
 for(const [i,k] of ['POOL_A','POOL_B','POOL_C'].entries())$(`count-${['a','b','c'][i]}`).textContent=state.pools?.[k]?.length||0;
 renderStocks();
 $('provenance').innerHTML=[['信息截点',state.as_of_time],['行情基准日',state.quote_date],['采集完成',state.finished_at],['Run ID',state.run_id?.slice(0,16)],['Google Docs',state.google_docs?.status||'NOT_CONFIGURED'],['AI增强',state.ai?.status||'DISABLED']].map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
 const sources={};for(const s of state.source_logs||[]){const old=sources[s.source_name]||{ok:0,total:0};old.total++;if(s.success)old.ok++;sources[s.source_name]=old;}
 $('source-list').innerHTML=Object.entries(sources).map(([k,v])=>`<div class="source-item"><span>${esc(k)}</span><span>${v.ok} / ${v.total} 成功</span></div>`).join('')||(demo?'<div class="source-item">SIMULATED · 仅用于功能验收</div>':'<div class="source-item">尚无采集记录</div>');
 $('missing-factors').innerHTML=(state.missing_factors||['等待首份数据质量报告']).map(s=>`<li>${esc(s)}</li>`).join('');
 $('eliminations').innerHTML=(state.eliminations||[]).slice(0,100).map(s=>`<li>${esc(s.stock_code||s.code)} · ${esc(s.reason)}</li>`).join('')||'<li>暂无淘汰记录</li>';
 $('warnings').innerHTML=(state.warnings||[]).map(s=>`<li>${esc(s)}</li>`).join('');
 const evals=Object.entries(state.evaluation||{}).filter(([,v])=>v.sample_size>0);
 $('evaluation').innerHTML=demo?'<div class="eval-row">演示结果不计入真实因子有效性统计</div>':evals.length?evals.map(([k,v])=>`<div class="eval-row"><span>${esc(k)} · ${v.sample_size} 个观察</span><span>均值 ${pct(v.average_return)}</span></div>`).join(''):'<div class="eval-row"><span>真实样本</span><b>等待前瞻积累</b></div><div class="eval-row"><span>胜率 / 平均收益 / 回撤</span><span>— / — / —</span></div>';
 if(downloadURL)URL.revokeObjectURL(downloadURL);downloadURL=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:'application/json'}));$('download').href=downloadURL;
}
function renderStocks(){
 const group=(state.pools?.[activePool]||[]).filter(s=>(!$('sector-filter').value||s.sector===$('sector-filter').value)&&(!$('position-filter').value||s.position_type===$('position-filter').value)&&(!$('risk-filter').value||s.risk===$('risk-filter').value)).sort((a,b)=>(b[$('sort').value]??-1)-(a[$('sort').value]??-1));
 $('shown-count').textContent=`${group.length} 只候选`;
 $('stock-rows').innerHTML=group.map(s=>`<tr><td><button class="stock-name" data-code="${esc(s.stock_code)}">${esc(s.stock_name)}<small>${esc(s.stock_code)}</small></button></td><td>${esc(s.sector)}</td><td>${num(s.price)}<span class="second-line ${color(s.change_pct)}">${pct(s.change_pct)}</span></td>${[5,10,20].map(n=>`<td class="${color(s['return_'+n+'d'])}">${pct(s['return_'+n+'d'])}</td>`).join('')}<td>${pct(s.distance_ma20)}</td><td>${num(s.atr)}<span class="second-line">${num(s.natr)}%</span></td><td>${pill(s.position_type)}<span class="second-line">${esc(s.risk)}风险</span></td><td>${num(s.sector_score,0)}</td><td class="stock-score">${num(s.total_score,1)}</td></tr>`).join('')||'<tr><td colspan="11" class="empty">当前没有满足条件的候选。<br>保留空池，也是规则系统的一种判断。</td></tr>';
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
 const fields=[['现价',s.price],['MA5',s.ma5],['MA10',s.ma10],['MA20',s.ma20],['MA60',s.ma60],['ATR14',s.atr],['NATR %',s.natr],['MoveATR',s.move_atr],['板块分',s.sector_score],['交易性',s.tradability_score],['量比',s.volume_ratio],['换手率 %',s.turnover]];
 $('detail-body').innerHTML=`<h2>${esc(s.stock_name)} <small>${esc(code)}</small></h2><p>${esc(s.sector)} · ${esc(s.position_type)} · ${esc(s.atr_state)} ATR · ${esc(s.risk)}风险<br>行情时间 ${esc(s.timestamp)} · 来源 ${esc(s.source)} · 价格序列未经复权</p><div class="detail-grid">${fields.map(([k,v])=>`<div>${esc(k)}<b>${num(v)}</b></div>`).join('')}</div>${chart(s.bars)}<div class="detail-columns"><div><h3 class="detail-heading">最关键正因子</h3><p>${esc(s.positive_factor)}</p><h3 class="detail-heading">验证条件</h3><p>${esc(s.validation_condition)}</p></div><div><h3 class="detail-heading">最关键负因子</h3><p>${esc(s.negative_factor)}</p><h3 class="detail-heading">失效条件</h3><p>${esc(s.invalidation_condition)}</p></div></div><p>量价：${esc(s.volume_type)}。主观上涨/连板概率：${s.subjective_probability==null?'未输出（无已校准模型）':`${num(s.subjective_probability*100,0)}%（AI未校准）`}。交易性分：${num(s.tradability_score,0)}。100分深度评分：${num(s.deep_score)}。</p><h3 class="detail-heading">事件与催化</h3>${(s.events||[]).map(e=>`<div class="event"><a href="${safeURL(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a><br><small>${esc(e.source)} · ${esc(e.publish_time)} · ${esc(e.expectation||'证据不足')} · ${e.verified?'已核验':'待正文核验'}</small></div>`).join('')||'<p>无已确认事件；不按新闻条数加分。</p>'}<h3 class="detail-heading">历史排名</h3><p>${(s.rank_history||[]).map(r=>`${esc(r.date)} ${esc(r.stage)} #${r.rank}（${num(r.score)}）`).join(' → ')||'首次观察，等待后续验证。'}</p>`;
 $('detail').showModal();
}
document.querySelectorAll('[data-pool]').forEach(b=>b.addEventListener('click',()=>{activePool=b.dataset.pool;document.querySelectorAll('[data-pool]').forEach(x=>x.setAttribute('aria-selected',String(x===b)));renderStocks();}));
for(const id of ['sector-filter','position-filter','risk-filter','sort'])$(id).addEventListener('change',renderStocks);
$('refresh').addEventListener('click',load);$('close-detail').addEventListener('click',()=>$('detail').close());
$('detail').addEventListener('click',e=>{if(e.target===$('detail')){const r=$('detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('detail').close();}});
load();
