NAMES={'POOL_A':'A 涨停晋级观察','POOL_B':'B 趋势观察池','POOL_C':'C 独立催化池'}
def fmt(x,digits=2):return '—' if x is None else f'{x:.{digits}f}' if isinstance(x,(float,int)) else str(x).replace('|','／').replace('\n',' ')

def stage_markdown(run):
    if run.get('stock_research'): return stock_markdown(run)
    m=run.get('market',{})
    lines=[f"## {run['stage'][:2]}:{run['stage'][2:]} {run['stage_label']}",f"\n时间戳：{run['as_of_time']} ｜ Run ID：{run['run_id']}",f"\n模式：{'演示模拟数据，不是市场判断' if run['mode']=='demo' else '真实数据任务'}",f"\n状态：{run['status']} ｜ 数据质量：{run['data_quality']['status']}",f"\n市场：{m.get('environment') or '数据不足，不评级'} ｜ 市场广度参考分：{fmt(m.get('score'))}",f"行情基准日：{run.get('quote_date','—')}；评分口径：{m.get('basis','—')}。"]
    if run['mode']=='retrospective':
        lines[2]='\n模式：历史收盘复盘（含事后板块分类限制；非时点回测）'
    if run['mode']=='bootstrap':
        lines[0]='## 周末初始化快照'
        lines[2]='\n模式：首次启动用初始化数据；不是历史晚间任务记录'
    for warning in run.get('warnings',[]):lines.append(f'\n- {warning}')
    if run.get('event_cutoff_time'):
        lines.append(f"\n公告观察截点：{run['event_cutoff_time']}；行情截点保持上方时间戳，首次观察不等同于公告发布时间。")
    if run.get('afternoon_message'):lines.append('\n**'+run['afternoon_message']+'**')
    w=run.get('wudao')
    if w:
        lines += ['\n### 悟道热点参考', f"状态：{w['status']}；行情日期：{w['trade_date']}。原始题材强度不是系统百分制评分。"]
        for key,label in [('featured','题材强度榜'),('industry','行业涨幅榜')]:
            panel=w.get(key)
            if panel:
                lines += [f"\n{label}；快照：{panel['snapshot_time']}", '|板块|强度|涨跌幅|','|---|---:|---:|']
                for row in panel['rows']:
                    lines.append(f"|{fmt(row['themeName'])}|{fmt(row.get('strength'),0)}|{fmt(row.get('pctChg'))}%|")
        if w.get('errors'): lines.append('采集缺口：'+','.join(w['errors']))
        if 'member_requests' in w:
            lines.append(f"本次成分请求 {w['member_requests']} 次，复用带时间标记的分类缓存 {w.get('member_cache_hits',0)} 个；热点榜仍为本次请求。")
    lines+=['\n### 已覆盖成分规则评分','\n|板块|类型|分数|状态|历史因子覆盖|','|---|---|---:|---|---:|']
    for s in run.get('sectors',[])[:10]:lines.append(f"|{fmt(s['name'])}|{s['kind']}|{fmt(s['score'])}|{s['state']}|{s['factor_coverage']:.0%}|")
    for pool,label in NAMES.items():
        lines += [f'\n### {label}','\n|排名|代码 名称|板块|位置|规则分|计分覆盖|主观概率|ATR状态|','|---:|---|---|---|---:|---:|---|---|']
        group=run.get('pools',{}).get(pool,[])
        for s in group:
            probability='未校准/未输出' if s.get('subjective_probability') is None else f"{s['subjective_probability']:.0%}（主观）"
            lines.append(f"|{s['rank']}|{s['stock_code']} {fmt(s['stock_name'])}|{fmt(s['sector'])}|{s['position_type']}|{fmt(s['total_score'])}|{fmt(s.get('score_coverage',0)*100,0)}%|{probability}|{s['atr_state']}|")
        if run.get('pool_notes',{}).get(pool):lines.append('\n'+run['pool_notes'][pool])
        if not group and not run.get('pool_notes',{}).get(pool):lines.append('\n无符合条件候选，不补足数量。')
        for s in group:
            if s.get('derived_board_count') is not None: lines.append(f"日线推导连续涨停：{s['derived_board_count']}；非供应商确认板数，特殊交易及历史除权未完全覆盖。")
            lines += [f"\n#### {s['stock_code']} {s['stock_name']}",f"- 板数：{fmt(s.get('board_count'))}；Market/Sector：{fmt(s.get('market_score'))}/{fmt(s.get('sector_score'))}；已识别技术风险：{s['risk']}；事件核验：{s.get('event_review_status','未完整核验')}",f"- 5/10/20日：{fmt(s.get('return_5d'))}% / {fmt(s.get('return_10d'))}% / {fmt(s.get('return_20d'))}%；MA20距离：{fmt(s.get('distance_ma20'))}%",f"- 正因子：{s['positive_factor']}",f"- 负因子：{s['negative_factor']}",f"- 验证：{s['validation_condition']}",f"- 失效：{s['invalidation_condition']}"]
            if s.get('wudao_themes'):lines.append('\n- 悟道题材归属：'+'、'.join(s['wudao_themes']))
            if s.get('validation_label'):lines.append(f"- 午盘验证：{s['validation_label']}；上午真实涨跌 {fmt(s['morning_return'])}%")
    if run.get('validations'):
        lines+=[f"\n### {'08:00' if run['stage']=='1200' else '08:30'}全部候选验证"]
        for s in run['validations']:lines.append(f"- {s['stock_code']} {s['stock_name']}：{s['validation_label']}；{fmt(s.get('morning_return'))}%")
    if run.get('events'):
        lines.append('\n### 公告与风险线索（逐条标注核验状态）')
        for e in run['events']:
            when = e['publish_time'][:10]+'（仅日期）' if e.get('publish_time_precision')=='date' else e['publish_time']
            lines.append(f"- {e['stock_code']} · {fmt(e['title'])} · {when} · {e['source']} · {e['url']} · {'已核验' if e.get('verified') else '待核验'}")
            if e.get('verification'):
                v=e['verification']; lines.append(f"  - 正文证据：{v.get('evidence',v.get('reason',''))}；{v.get('score_basis','')}")
    lines+=['\n### 因子可用性', '|指标|状态|覆盖|原因|','|---|---|---:|---|']
    for item in run.get('factor_statuses',[]):
        lines.append(f"|{fmt(item['label'])}|{fmt(item['status'])}|{fmt(item['coverage']*100,0)+'%' if item.get('coverage') is not None else '—'}|{fmt(item['reason'])}|")
    if not run.get('factor_statuses'): lines.append('、'.join(run.get('missing_factors',[])))
    lines+=['\n### 淘汰记录']
    for s in run.get('eliminations',[])[:40]:lines.append(f"- {s.get('stock_code',s.get('code'))}：{s.get('reason',s.get('exclusion_reason'))}")
    lines+=['\n这是规则研究记录。评分和主观概率不是收益承诺；没有可靠数据时不输出交易候选。']
    return '\n'.join(lines)+'\n'

def stock_markdown(run):
    from src.research.stocks import LABELS
    research=run['stock_research']
    lines=[f"## {run['stage_label']} · 个股研究",f"\n行情日期：{run.get('quote_date')}；报告截点：{run['as_of_time']}。",
           f"\n{research['note']}",f"\n市场背景：{run.get('market',{}).get('environment') or '未确认'}。市场全景与连板天梯：https://stock.quicktiny.cn/ai",
           f"\n悟道本阶段调用状态：{run.get('wudao',{}).get('status','未记录')}。"]
    for pool,label in LABELS.items():
        lines.append(f'\n### {label}')
        if not run['pools'].get(pool): lines.append('本阶段暂无满足条件的个股，不补足数量。')
        for s in run['pools'].get(pool,[]):
            r=s['research'];p=r['price_plan'];c=r['catalyst']
            lines += [f"\n#### {s['stock_name']} {s['stock_code']}",f"\n**{r['headline']}**\n\n{r['conclusion']}",
                      f"\n价格计划：{p['label']}。{p['trigger']}",
                      f"\n失效参考：{fmt(p.get('invalidation_price'))}；行情时间：{p.get('quote_time')}。",
                      f"\n催化判断：{c['headline']}。{c['conclusion']}",f"\n下一步核验：{c.get('next_check','待补充')}",
                      f"\n跟踪变化：{r['change']['label']}。"]
            if p.get('reward_risk_to_resistance') is not None: lines.append(f"至20日高点的空间/失效距离 {fmt(p['reward_risk_to_resistance'])}；高点只是阻力参考，不是目标收益。")
    lines.append('\n### 公告的经营含义')
    for c in research.get('catalyst_reviews',[]):
        lines += [f"\n**{c['stock_name']} {c['stock_code']}：{c['headline']}**",c['conclusion'],f"下一步：{c['next_check']}"]
        for source in c.get('sources',[]): lines.append(f"依据：{source['url']} （{source['published_at']}）")
    if run.get('transitions'):
        lines.append('\n### 暂停跟踪')
        lines += [f"- {s['stock_code']}：{s['reason']}" for s in run['transitions']]
    lines += ['\n### 数据边界', f"历史指标成功数：{research.get('coverage',{}).get('factor_ready','未记录')}；只代表本次预算样本。",
              '价格区间是条件研究，不保证可成交；未经完整公司行动核验，遇除权、重大新信息或下一报告需重算。',
              '公告仅限当前扫描范围，未发现不等于没有风险。']
    return '\n'.join(lines)+'\n'

def daily_markdown(day,runs):
    parts=[f'# {day} A股智能分析\n']
    stages=['0800','1200','2200'] if any(s in runs for s in ('0800','1200','2200')) else ['0730','0830','1135','1600','2130']
    for stage in stages:
        if stage in runs:parts.append(stage_markdown(runs[stage]))
        else:parts.append(f"## {stage[:2]}:{stage[2:]}\n\n尚未运行。\n")
    return '\n'.join(parts)
