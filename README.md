# MANSON A-Share Intelligence System

一个无需常驻服务器的个人 A 股研究工作台。程序从市场广度、板块、趋势、位置和风险逐步缩小候选范围，保留每次判断与后续结果。它不是普通资讯网站，也不会因为新闻多就加分。

**当前交付：MVP 已上线，Actions/Pages 和 Google Docs 已绑定，并通过云端读写与休市运行验证。正式交易日全链路仍待首个收盘扫描后验收；模拟演示不是真实行情。**

正式工作台：https://manson9150-a11y.github.io/manson-ashare/ 。上线证据见 [部署记录](docs/DEPLOYMENT_CHECKLIST.md)。

## 1. 它怎样运行

```text
GitHub Actions 五个时间节点
  → 免费公开 Adapter + 独立备用源
  → 时间戳 / 交易日 / 缺失 / 异常 / 冲突检查
  → Market Score → 行业及概念 Sector Score
  → 有限候选历史日线 → MA / ATR / 位置 / 风险
  → 三个独立候选池 → 少量事件核验 → 可选 AI
  → Markdown + JSON + Parquet历史 + Google Docs补传队列
  → GitHub Pages静态Dashboard
```

生产只需要 GitHub 和一个浏览器。Mac 关闭后，GitHub 上的任务仍可运行。Python 只做定时批处理，不启动长期 Python Web 服务。Dashboard 是 HTML/CSS/JavaScript，读取静态 JSON，无需登录或数据库服务器。

## 2. 先看工作台

部署后打开 GitHub Pages 给出的地址。首页默认展示**正式数据**，没有正式任务时保持空白状态；右上角“查看演示”打开 `?demo=1`，所有页面都有模拟标识。

首页包含市场环境、数据质量、板块Top10、三个候选池、位置数量、来源日志与因子缺口。可以按板块、位置、风险过滤，按综合分、交易性或板块分排序。点击股票查看最近日线蜡烛图、MA/ATR、事件、验证条件和失效条件。

本机临时预览（仅开发时需要）：

```bash
python -m http.server 8787 --bind 127.0.0.1 --directory dashboard
```

浏览器打开 `http://127.0.0.1:8787/`；这不是生产服务。

## 3. 每个时间点做什么

全部业务时间使用 `Asia/Shanghai`。

|北京时间|任务|唯一正式前序|输出|
|---|---|---|---|
|07:30|隔夜确认|上一交易日21:30|最多12只，上调/维持/下调/淘汰|
|08:30|盘前终审|当天07:30|最多10只，不重新海选|
|11:35|午盘确认|当天08:30|逐一验证Top10，S/A/B/C/D，最多5只|
|16:00|收盘全市场扫描|独立启动新一轮|A连板接力、B趋势启动、C独立催化|
|21:30|晚间二筛|当天16:00|A池最多15只，B/C同步更新|

07:30、08:30和21:30复用正式前序的收盘行情，只更新事件；**第一版海外数据增强未接入，因此盘前市场分仍是上一收盘的参考分，不冒称隔夜新预测**。午盘重新获取全市场快照并只验证早盘名单。

首次启用应从一个交易日16:00开始。缺少21:30前序时，第二天07:30不会改用16:00结果。缺少可靠行情时，允许空池。

首次启动另支持显式周末初始化：用户要求后，于实际周末时点用已完成的收盘复盘检查原候选并尝试刷新事件，保存到 `data/bootstrap/<目标交易日>.json`。只有指定交易日07:30且正式前序完全不存在时可使用；失败的正式前序不会被覆盖，后续阶段保留初始化来源和公告缺口，不计入常规因子效果统计。2026-09-07的初始化已于2026-09-06建立，包含30只观察候选；首次公告请求失败后，已接入巨潮并成功补入31条公告；明早继续刷新。正式收盘扫描完成后建立新的正常数据链。

另经用户要求，安排2026-09-06 21:30周末晚间二筛：使用初始化名单与9月4日收盘行情，刷新公告后按晚间规则筛选；报告日期为实际周末日期，网站首页与Google文档正常发布，成功后更新9月7日前序。仅 `weekend_evenings` 明确配置的日期可运行，保留21:30至23:59窗口；专用调度还校验完整年份日期，其他年份不会因此额外生成报告。重复运行复用已完成快照，不重复生成报告。

## 4. 最少部署步骤（无需Linux、Docker）

### A. 把这个文件夹放进你的GitHub仓库

推荐安装 GitHub Desktop，登录你的 GitHub 账号：

1. `File → Add Local Repository`，选择这个 `manson-ashare` 文件夹。
2. 点击 `Publish repository`，仓库名建议 `manson-ashare`，默认分支使用 **main**。
3. 若要尽量零费用，选公开仓库，先确认愿意公开派生因子、候选和报告；不要放账户持仓、身份证件或密钥。选择私有仓库前查看账号的 Actions 配额和 Pages 支持。

也可以使用已登录的 GitHub CLI：

```bash
gh repo create manson-ashare --public --source=. --remote=origin --push
```

不要上传 `.venv`、`.env`、服务账号私钥文件。项目已有 `.gitignore`。

### B. 开启Actions和Dashboard

1. 仓库 `Settings → Actions → General`：允许工作流运行，`Workflow permissions` 选择 **Read and write permissions**。
2. `Settings → Pages → Build and deployment → Source` 选择 **GitHub Actions**。
3. `Actions → Publish Dashboard → Run workflow` 首次发布。完成后在 Pages 设置页点击实际站点地址。
4. `Actions → Tests and offline dry run` 应显示绿色。
5. `Daily A-share Research` 已预置五个定时任务；上传到默认分支后运行。

GitHub 定时任务可能延迟甚至漏触发，并不保证准点。程序记录计划时间、实际信息截点和延迟；错过可接受时间窗就停止该阶段，禁止把下午数据倒填早盘。公开仓库长期无活动时也可能停用定时任务，请关注 GitHub 的任务通知。[官方说明](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)

免费额度和托管政策可能变化。公开仓库是本项目的零服务器成本首选，AI默认关闭；没有付费行情API。代码不会购买服务。[GitHub Actions计费说明](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

### C. 连接Google Docs（可稍后做）

正式研究日志使用你的一份现有Google文档，按日期增加一章，每章预留五个阶段。已经找到的现有文档可优先使用“**A股短线全景研究档案**”；文档ID不写进公开仓库。

1. 在 Google Cloud Console 建一个项目，启用 **Google Docs API**。
2. 创建一个 **Service Account**，创建 JSON 类型密钥，安全保存。
3. 把你的研究主文档共享给 JSON 中的 `client_email`，权限为“编辑者”。无需把整个 Google Drive 共享给它。
4. 在 GitHub 仓库 `Settings → Secrets and variables → Actions → New repository secret` 增加：

|Secret|填写内容|
|---|---|
|`GOOGLE_DOC_ID`|文档链接中 `/d/` 与 `/edit` 之间的那一段|
|`GOOGLE_SERVICE_ACCOUNT_JSON`|完整服务账号JSON，作为Secret粘贴，绝不提交文件|

Codex中能读取Google Drive，不代表GitHub Actions获得了你的OAuth认证。云端必须单独配置上述认证；本地连接的Google私钥不会也不应被导出到仓库。

没有认证时，分析、Markdown和Dashboard继续生成，成功完成的阶段报告进入 `data/pending/`；数据不足的降级报告保留本地，不占用正式阶段标记。下一次任务自动补传。写入使用版本校验；同一天同一阶段有完成标记，网络响应丢失后重试不会重复追加。不要手动删除 `[MANSON:...]` 标记。

只更新主文档首个标签页，不改写已有研究章节。阶段报告目前以可读文本承载详细Markdown表格，日期和阶段使用原生标题；复杂原生Google表格排版留待后续。

[Google Docs API写入与版本控制](https://developers.google.com/workspace/docs/api/how-tos/named-ranges)

### D. 可选AI（默认不调用、不产生AI费用）

核心筛选不需要 `OPENAI_API_KEY`。

有意启用时，再执行三项设置：

- Secret：`OPENAI_API_KEY`。
- Repository variable：`OPENAI_MODEL`，填你有权限使用且支持Structured Outputs的模型名。
- `config/settings.yaml`：`ai.enabled: true`。

AI最多处理25个已有事件证据的规则候选，输出严格JSON Schema并做代码二次校验。计算指标始终由Python产生。没有证据的板质量、龙虎榜、概率等必须为空；八个领域齐全才输出完整100分深度评分。主观概率明确标为“未校准”，不等于历史胜率。

[OpenAI Structured Outputs官方文档](https://developers.openai.com/api/docs/guides/structured-outputs)

## 5. 手动运行与查看失败

在 GitHub `Actions → Daily A-share Research → Run workflow` 选择阶段。无需Mac开机。

- `0730 / 0830 / 1135 / 1600 / 2130`：受时间窗和前序状态校验。
- `full_pipeline`：正式模式只执行**当前合法时间窗**内的任务，不用晚间数据重建当天早盘。
- 非交易日：正常结束并记录 `NON_TRADING_DAY`，不产生伪行情报告。

点开失败任务查看步骤日志；页面底部显示质量和来源失败情况。任务即使失败也尝试提交已产生结果，另有14天保留的 `research-运行编号` 下载包，包含待补传队列和报告。Git推送失败时可从该下载包恢复。

|状态|含义|处理|
|---|---|---|
|COMPLETE + YELLOW|可用基础筛选，增强字段有缺口|看缺口清单，不把基础分理解为完整模型|
|DEGRADED + RED|关键覆盖/历史/板块不足|候选清空，检查来源，稍后在合法时间窗重跑|
|MISSING_PREDECESSOR|正式上一阶段不存在|从下一次16:00重新建立闭环|
|OUTSIDE_STAGE_WINDOW|已错过时间窗|等待下一合法阶段，不能倒填|
|CALENDAR_UNVERIFIED|年份未核验|按交易所公告更新日历|
|NOT_CONFIGURED / PENDING|Docs没认证或写入失败|设置Secrets或排查权限；本地报告还在|

完整阶段结果一旦成功便冻结，重复运行返回同一个Run ID，保护后续状态。失败结果可在时间窗内重试。若要更改已完成的历史研究，应作为新研究版本设计，不能删改历史来提高胜率。

## 6. 本地开发或离线验收

需要Python 3.12以上。无需行情账号：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .
pytest -q
python -m src.cli --demo --stage full_pipeline --date 2026-09-04
```

模拟会先生成前一日16:00/21:30，再完整执行当日五阶段，输出在 `artifacts/demo/`。它只更新 `dashboard/data/demo.json`，不写正式历史或Google Docs，不是数据源fallback。

公开源只读实测：

```bash
python scripts/probe_sources.py
```

生产阶段本地调试（需要真实交易日和合法时间窗）：

```bash
python -m src.maintenance
python -m src.cli --stage 1600
```

`src.maintenance` 提前取得带 `observed_at` 的行业成分元数据。主任务只使用信息截点前已观察到、且7日内的映射。元数据不含被冒认为当日行情的网页涨跌。

历史研究只能重放存档：

```bash
python -m src.cli --replay --date 2026-09-04 --stage 0830
```

没有存档就拒绝，绝不从当前API反推。配置 `.env.example` 供本地参考；本工具不自动加载 `.env`，如需本地认证，应通过终端环境变量或秘密管理器注入。

## 7. 当前数据源与备用关系

|用途|首选|备用|缺失时|
|---|---|---|---|
|全市场股票目录|东方财富|腾讯公开排行榜 → 新浪目录|无法确定市场覆盖则RED|
|带原始时间戳快照|东方财富|腾讯 → 新浪|逐源校验，旧日期也触发fallback|
|历史日线|东方财富未复权OHLCV和成交额|腾讯未复权OHLCV|腾讯不提供的成交额保持null|
|行业成分|东方财富行业字段|预先观察的新浪49行业映射|未映射个股排除|
|概念成分|东方财富主要概念成分|尚无独立备用|明确降低覆盖，不猜测主题归属|
|涨停池、板数、封板信息|东方财富涨停池|腾讯明确涨停价可确认当日涨停|板数/封单指标缺失留空|
|公告事件|巨潮官方公开查询|东方财富公告 / 手工核验事件 / 前序已知事件|标题只作风险预警；不自动给正催化打满分|
|交易日历|上交所2026年度公告|本地已核验日历|未知年份停止正式任务|

源访问基于公开可读取端点，不绕验证码、登录、限流或付费墙。HTTP 401/403/429不做绕过与立即重试；网络及5xx短重试，超时和熔断隔离单源故障。接口可能变更，没有SLA。

2026-09-05实测：腾讯快照/日线、新浪快照、东方财富日线可用；东方财富全市场快照连接失败；新浪49行业元数据采集成功（3005个不同代码，非全市场完整行业覆盖）。实测只证明当时该接口返回正确结构，不证明下一交易日的全市场可用率。

接口字段依据[AKShare公开源码和接口目录](https://github.com/akfamily/akshare)，本项目直接调用受控HTTP适配器；**当前没有把AkShare本身作为独立备用源**，因为它常与同一上游共用故障。QuickTiny仅提供禁用适配器，等待公开可用性和条款核验。巨潮/交易所原始公告正文、财联社和海外行情暂列TODO。

[2026交易所日历来源](https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml)

## 8. 分数到底表示什么

- **Market Score**：MVP使用全市场上涨比例65% + 涨跌中位数映射35%，0–100。强≥70，正常45–69，偏弱<45。完整连板情绪链、指数及外部变量当前显示缺失。
- **Sector Score**：广度50%、涨幅中位数30%、MA20上方比例20%。MA20成分历史覆盖不到70%时，该项不用于板块分，缺失项不使用，并标注因子覆盖率。板块多日收益目前是已采历史成分的中位数，不是完整行业指数收益。
- **程序综合分**：趋势30%、板块30%、位置25%、量能15%，减风险惩罚。可用维度覆盖率 `score_coverage` 单列；缺失维度不伪造。该基础分与完整深度100分是不同口径。
- **深度100分**：板质量20、题材20、梯队15、资金15、催化10、龙虎榜10、外部5、风险收益5。缺失领域留空，不能伪装完整评分。
- **ATR14**：Wilder算法，首14个TR均值为种子，然后递推；NATR=ATR/价格×100，MoveATR=当日绝对百分比涨跌/NATR。过热扣分，高位候选即使被观察，其追涨交易性为0。
- **成交额倍数**：当前成交额除以**此前**5/10/20个完整交易日均值。午盘没有同时间基准时不计算，避免把半日成交额当成缩量。
- **重复因子**：Market仅用于风险环境，行业广度与个股趋势分开；新闻条数不加分。MA结构与累计涨幅有统计相关性，仍需未来样本消融验证，不能声称已消除一切相关性。

硬规则和阈值在 `config/settings.yaml`。最常改：`market`市场阈值、`sector`强弱、`position`位置、`atr`过热倍数、`candidate_pool`上限、`risk`风险、`sources.max_history_stocks`历史请求预算。改完运行测试和模拟，再提交GitHub。

## 9. 历史、质量与回测

每阶段保留因子Parquet、候选JSON、阶段结果和Markdown。16:00额外保存压缩的全市场每日快照，用于真实结果追踪。仅在最新滚动缓存保留候选最多65根日线用于图表，历史阶段JSON不重复保存K线；不提交分钟原始数据。

目录类似：`data/history/2026/09/04/1600/`。`data/history/outcomes.json` 逐步积累次日开盘、收盘、高低、是否涨停、3日和5日表现。缺一交易日的数据会保持空值，不能把“下一条存在的数据”当作次日。

统计按阶段/池分组：胜率、平均/中位收益、日等权观察组合最大回撤、次日涨停率、Top3/Top5命中率。命中定义为次日收盘上涨，数据不足时不展示胜率。不是可成交的资金回测：尚未计入T+1、涨停买不到、滑点、费用、除权现金分红及完整退市样本。

实时行情先检查股票代码、交易日、原始时间、OHLC、成交状态、极端值、缓存和冲突。可靠性官方优先，同级取更新时间更晚者。未来数据被拒绝；`publish_time > as_of_time` 的事件不进入引擎。未知时间戳不能用抓取时间冒充。

日线使用未复权价格；出现大幅断点时保守排除。尚未完整识别所有除权行为，因此存在误筛/漏筛风险。严谨历史回测需要后续的时点复权和存活偏差处理。

### 独立收盘复盘

[2026-09-04 收盘复盘](https://manson9150-a11y.github.io/manson-ashare/?replay=2026-09-04)已保存；完整说明见 [复盘报告](reports/replays/2026-09-04.md)，30只规则候选见 [CSV](reports/replays/2026-09-04-candidates.csv)。行情、250只股票的日线、因子、分类、规则及核验记录保存在 `data/replays/2026-09-04/`。

收盘复盘接受目标交易日16:00之后的真实收盘行情更新，保留来源时间，不把后续交易日的价格混入；这与重建“16:00当时可知信息”的时点回测不同。实时五阶段仍保留各自的时间护栏。复盘采用经用户同意的事后行业分类，覆盖47.4%；250只日线中195只缺少成交额历史，历史公告风险也未完整核验，因此不能视为全市场完整回测。

本地独立运行示例（已有冻结输入时复用；输出不会覆盖正式历史或写入主Google文档）：

```bash
.venv/bin/python -m src.retrospective --date 2026-09-04 \
  --output artifacts/retrospective-2026-09-04 \
  --membership data/replays/2026-09-04/membership.json \
  --allow-current-membership
```

此入口要求可取得目标日期行情，或输出目录中已有对应冻结原始输入；不是任意历史日期的自动回测下载器。静态复盘入口为 `?replay=YYYY-MM-DD`，仅加载对应已发布快照，不回退到实时或模拟数据。

本次历史复盘已单独补写主Google文档的“历史复盘归档（补写）”章节；历史复盘命令仍不会自动写入正式五阶段占位。正式任务完成时，网页更新与Google文档归档并行使用；文档写入失败保留待补传队列。

## 10. 项目目录

```text
src/
  collectors/       公开源、重试、熔断、模拟数据
  normalizers/      行情和日线质量、时间护栏
  factors/          MA / Wilder ATR / 多周期收益
  market/ sectors/  市场与板块引擎
  stocks/ risk/     个股综合、位置与风险
  screening/        三候选池、前序状态与午盘验证
  catalysts/ ai/    去重、预期差规则、可选严格JSON AI
  reports/          阶段和每日Markdown
  google_docs/      幂等写入和持久待补传队列
  evaluation/       前瞻结果积累和基础统计
  utils/            日历、时区、原子JSON写入
  pipeline.py       阶段编排与模块隔离
  maintenance.py    带观察时间的行业元数据刷新
  cli.py            本地/Actions统一入口
config/             筛选配置、已核验日历、人工事件
dashboard/          可直接发布的静态前端及脱敏派生JSON
data/               轻量历史、最新结果、Docs待补传
reports/            日报和Run ID摘要
scripts/            真实源探测与浏览器验收
tests/              可脱网运行的单元与集成测试
.github/workflows/  五时点流水线、CI、静态发布
```

## 11. 怎么增加数据源或因子

新数据源继承 `src/collectors/base.py` 的 Adapter，实现 `fetch()` 和 `normalize()`，配置 `source_name`、可靠性及备用优先级。`health_check()`继承默认实现或按接口覆盖。只在可靠的原始时间戳上建模；把该源加入 `Pipeline` 的 Collector，补上失败和过期数据测试。

新增因子应是可脱网测试的纯函数，接收标准化OHLCV/事件，不直接抓网页；在 `technical()` 或对应引擎汇总，在配置里给权重/阈值，在报告注明所需字段及缺失行为。修改信号后使用未来真实样本验证，不通过删除历史或倒填数据提高效果。

新的官方事件可写 `config/events.json`，符合 `src.models.Event`。`verified=true` 只能用于已人工核验的公告，不要因为标题中含“合作”就标记重大催化。

## 12. 当前限制与下一步

完整透明验收表见 `docs/ACCEPTANCE.md`，待办见 `docs/TODO.md`。

最值得先增加三项：

1. 原始官方公告全文、龙虎榜和海外变量，做跨来源时间戳核验，提升晚间与隔夜阶段的信息增量。
2. 完整板块成分日线的增量存储、复权事件和同时间午盘成交额，提升数据覆盖与位置判断可靠性。
3. 积累真实候选至少数十个交易日后做分层因子消融、成本/涨跌停约束回测与概率校准，再调整权重。

Google主文档内容逐年增大后可以按年度归档。Git历史较大时可在 `utils/io.py` 之上实现Storage接口切换对象存储；第一版尚未实现云数据库适配，不引入额外服务器。

免费数据源接入状态与限制见 [数据源说明](docs/DATA_SOURCES.md)。
