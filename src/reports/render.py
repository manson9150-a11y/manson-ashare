NAMES={'POOL_A':'A 连板接力池','POOL_B':'B 趋势启动池','POOL_C':'C 独立催化池'}
def fmt(x,digits=2):return '—' if x is None else f'{x:.{digits}f}' if isinstance(x,(float,int)) else str(x).replace('|','／').replace('\n',' ')

def stage_markdown(run):
    m=run.get('market',{})
    lines=[f"## {run['stage'][:2]}:{run['stage'][2:]} {run['stage_label']}",f"\n时间戳：{run['as_of_time']} ｜ Run ID：{run['run_id']}",f"\n模式：{'演示模拟数据，不是市场判断' if run['mode']=='demo' else '真实数据任务'}",f"\n状态：{run['status']} ｜ 数据质量：{run['data_quality']['status']}",f"\n市场：{m.get('environment') or '数据不足，不评级'} ｜ Market Score：{fmt(m.get('score'))}",f"行情基准日：{run.get('quote_date','—')}；评分口径：{m.get('basis','—')}。"]
    if run['mode']=='retrospective':
        lines[2]='\n模式：历史收盘复盘（含事后板块分类限制；非时点回测）'
    if run['mode']=='bootstrap':
        lines[0]='## 周末初始化快照'
        lines[2]='\n模式：首次启动用初始化数据；不是历史晚间任务记录'
    for warning in run.get('warnings',[]):lines.append(f'\n- {warning}')
    if run.get('afternoon_message'):lines.append('\n**'+run['afternoon_message']+'**')
    lines+=['\n### 板块强弱','\n|板块|类型|分数|状态|历史因子覆盖|','|---|---|---:|---|---:|']
    for s in run.get('sectors',[])[:10]:lines.append(f"|{fmt(s['name'])}|{s['kind']}|{fmt(s['score'])}|{s['state']}|{s['factor_coverage']:.0%}|")
    for pool,label in NAMES.items():
        lines += [f'\n### {label}','\n|排名|代码 名称|板块|位置|综合分|交易性|主观概率|ATR状态|','|---:|---|---|---|---:|---:|---|---|']
        group=run.get('pools',{}).get(pool,[])
        for s in group:
            probability='未校准/未输出' if s.get('subjective_probability') is None else f"{s['subjective_probability']:.0%}（主观）"
            lines.append(f"|{s['rank']}|{s['stock_code']} {fmt(s['stock_name'])}|{fmt(s['sector'])}|{s['position_type']}|{fmt(s['total_score'])}|{fmt(s['tradability_score'])}|{probability}|{s['atr_state']}|")
        if run.get('pool_notes',{}).get(pool):lines.append('\n'+run['pool_notes'][pool])
        if not group and not run.get('pool_notes',{}).get(pool):lines.append('\n无符合条件候选，不补足数量。')
        for s in group:
            lines += [f"\n#### {s['stock_code']} {s['stock_name']}",f"- 板数：{fmt(s.get('board_count'))}；Market/Sector：{fmt(s.get('market_score'))}/{fmt(s.get('sector_score'))}；风险：{s['risk']}",f"- 5/10/20日：{fmt(s.get('return_5d'))}% / {fmt(s.get('return_10d'))}% / {fmt(s.get('return_20d'))}%；MA20距离：{fmt(s.get('distance_ma20'))}%",f"- 正因子：{s['positive_factor']}",f"- 负因子：{s['negative_factor']}",f"- 验证：{s['validation_condition']}",f"- 失效：{s['invalidation_condition']}"]
            if s.get('validation_label'):lines.append(f"- 午盘验证：{s['validation_label']}；上午真实涨跌 {fmt(s['morning_return'])}%")
    if run.get('validations'):
        lines+=['\n### 08:30全部候选验证']
        for s in run['validations']:lines.append(f"- {s['stock_code']} {s['stock_name']}：{s['validation_label']}；{fmt(s.get('morning_return'))}%")
    lines+=['\n### 数据缺口', '\n'+ '、'.join(run.get('missing_factors',[])), '\n### 淘汰记录']
    for s in run.get('eliminations',[])[:40]:lines.append(f"- {s.get('stock_code',s.get('code'))}：{s.get('reason',s.get('exclusion_reason'))}")
    lines+=['\n这是规则研究记录。评分和主观概率不是收益承诺；没有可靠数据时不输出交易候选。']
    return '\n'.join(lines)+'\n'

def daily_markdown(day,runs):
    parts=[f'# {day} A股智能分析\n']
    for stage in ['0730','0830','1135','1600','2130']:
        if stage in runs:parts.append(stage_markdown(runs[stage]))
        else:parts.append(f"## {stage[:2]}:{stage[2:]}\n\n尚未运行。\n")
    return '\n'.join(parts)
