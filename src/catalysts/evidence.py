"""Discover outside the trend pool and verify narrow facts in official PDF text.
Unsupported/ambiguous/scanned documents remain unverified; titles never earn scores.
"""
from datetime import datetime, timedelta
from io import BytesIO
import hashlib
import re
from urllib.parse import urlparse
from src.catalysts.engine import deduplicate
from src.collectors.announcements import CninfoAnnouncementAdapter
from src.utils.calendar import TZ
from src.utils.io import write_json
from src.utils.io import read_json
from src.models import Event

RULE_VERSION = 'official_pdf_facts_v2'


def verify_text(event, text, observed_at):
    text = re.sub(r'\s+', '', text)
    audit = {'status': 'UNVERIFIED', 'rule_version': RULE_VERSION,
             'observed_at': observed_at.isoformat(), 'document_url': event.document_url,
             'text_sha256': hashlib.sha256(text.encode()).hexdigest()}
    def result(reason, **changes):
        return event.model_copy(update={'verified': False, 'impact_score': None,
            'verification': {**audit, 'reason': reason}, **changes})
    if not re.search(r'(?:证券|股票)代码[:：]?' + event.stock_code + r'(?!\d)', text[:1800]):
        return result('ISSUER_NOT_MATCHED')
    # Record adverse revisions before testing positive size thresholds. A large
    # remaining amount must not turn a shrinking existing order into new upside.
    reduction = re.search(r'(?:合同|工程)(?:总价|金额|价款|价)[^。；;]{0,50}?(?:调减|下调|减少|缩减)', text)
    if reduction:
        audit.update(business_direction='NEGATIVE_REVISION', contract_status='AMENDED',
                     analysis='公告披露合同规模调减。剩余金额不是新增订单；需核对已确认收入、未执行部分与回款，不能直接推算利润损失。')
        return result('CONTRACT_REDUCTION_REQUIRES_REVIEW')
    if any(w in event.title for w in ['更正', '补充', '风险', '终止', '解除', '减持', '框架', '意向', '诉讼']):
        return result('AMBIGUOUS_OR_RISK_TITLE')
    if re.search(r'(?:尚未|未)(?:正式)?(?:签订|签署)[^。；;]{0,16}?合同|尚未生效', text):
        audit.update(contract_status='NOT_CONFIRMED', analysis='公告存在尚未签约或生效的明确表述。中标、意向或预计金额仍需转成正式履约承诺，收入和回款尚未兑现。')
        return result('CONTRACT_NOT_CONFIRMED')
    if re.search(r'合同(?:已|已经|现已|被)(?:正式)?(?:终止|解除|取消)|(?:决定|已协商一致|双方协商一致)(?:终止|解除|取消)(?:该|上述|本)?合同', text):
        audit.update(business_direction='CANCELLED', contract_status='CANCELLED', analysis='正文出现合同终止或解除的明确状态，应先核对损失与剩余权利义务，不能认定新增利好。')
        return result('CONTRACT_NOT_CONFIRMED')
    if re.search(r'(?:公司|子公司)[^。；;]{0,100}?(?:签订|签署)[^。；;]{0,40}?合同', text):
        audit.update(contract_status='SIGNED_DISCLOSED', analysis='正文披露签约，但签约事实与重要性是两回事。需核对相对营收规模、交付验收、回款与利润率，合同总额不等于本期利润。')
    # A signed contract with quantified materiality against a FULL fiscal year's revenue.
    denominator = r'(?:最近一个会计年度|上一年度|上年度|上年|20\d{2}年(?:度)?)'
    pattern = (r'(?:本次|该|上述)?(?:合同|订单)(?:总)?金额.{0,50}?占(?:公司)?'
               + denominator + r'(?:经审计的?|合并报表)?营业收入(?:的|比例为|比例|为)?'
               r'([0-9]+(?:\.[0-9]+)?)%')
    match = re.search(pattern, text)
    if ('合同' in event.title or '订单' in event.title) and match and re.search(r'(?:公司|子公司).{0,100}?(?:签订|签署).{0,40}?合同', text):
        ratio = float(match.group(1))
        if 10 <= ratio <= 1000:
            evidence = match.group(0)
            audit.update(status='VERIFIED_RULE', rule='SIGNED_CONTRACT_REVENUE_10PCT',
                evidence=evidence, materiality_pct=ratio,
                score_basis='规则分：已签合同金额占完整年度营收10%以上为70分，20%以上为80分；不代表收益概率。')
            return event.model_copy(update={'verified': True, 'impact_score': 80 if ratio >= 20 else 70,
                'event_type': '重大合同', 'verification': audit})
    # Absolute materiality is an explicit alternative when the issuer does not
    # disclose the revenue ratio. Count only a signed revenue-generating contract,
    # never procurement spending, a framework, an unsigned bid or a target value.
    amount = re.search(r'合同(?:含税|不含税|总)?金额(?:为|[:：])(?:人民币)?([0-9,]+(?:\.[0-9]+)?)(万元|亿元|元)', text)
    effective = re.search(r'合同已(?:正式)?签署并生效', text)
    sale = re.search(r'销售合同|(?:公司|其|乙方).{0,25}(?:向其提供|出租|向甲方提供)', text)
    if ('合同' in event.title and amount and effective and sale):
        value = float(amount.group(1).replace(',', '')) * {'元':1,'万元':10000,'亿元':100000000}[amount.group(2)]
        if 1_000_000_000 <= value <= 1_000_000_000_000:
            duration = re.search(r'(?:租赁|履行|合同)(?:期限|期)(?:为)?([0-9]+)(个月|年)', text)
            audit.update(status='VERIFIED_RULE', rule='EFFECTIVE_SALES_CONTRACT_1BN',
                evidence=amount.group(0), contract_amount_yuan=value,
                contract_duration=duration.group(0) if duration else '未解析',
                score_basis='规则分70：已签署生效的销售合同总额至少10亿元。含税总额不等于当期收入或利润，营收占比未核验，长期履约存在风险。')
            return event.model_copy(update={'verified':True,'impact_score':70,
                'event_type':'重大合同','verification':audit})
    # Profit forecast: attributable net profit must be positive AND its conservative
    # growth bound >=50%. Negatives, yoy base effects and unrelated metrics do not pass.
    if '业绩预告' in event.title and not re.search(r'预亏|首亏|续亏|预减|扭亏|修正', event.title):
        profit = re.search(r'归属于上市公司股东的净利润(?:本报告期|本期|预计)?盈利[:：]?([0-9]+(?:\.[0-9]+)?)(?:万元|亿元)', text)
        growth = re.search(r'归属于上市公司股东的净利润.{0,180}?比上年同期增长[:：]?([0-9]+(?:\.[0-9]+)?)%', text)
        if profit and growth and float(profit.group(1)) > 0 and 50 <= float(growth.group(1)) <= 1000:
            audit.update(status='VERIFIED_RULE', rule='POSITIVE_PROFIT_FORECAST_GROWTH_50PCT',
                evidence=profit.group(0)+'；'+growth.group(0),
                score_basis='规则分70：归母净利润盈利且同比增长下限至少50%；公司预告未经审计，不等于已实现业绩。')
            return event.model_copy(update={'verified': True, 'impact_score': 70,
                'event_type': '业绩', 'verification': audit})
    return result('NO_SUPPORTED_MATERIAL_FACT; NEEDS_REVIEW')


class CatalystEvidence:
    def __init__(self, config, output):
        self.config = config.get('catalyst_evidence', {})
        self.adapter = CninfoAnnouncementAdapter(config, output/'data/latest/announcement_first_seen.json')
        self.verified_cache = output/'data/latest/verified_catalyst_cache.json'
        self.freshness_hours = config['catalyst']['freshness_hours']
        self.logs = []
        self.attempted = {}
        self.remaining = self.config.get('max_documents', 20)
        self.status = {'status': 'PENDING', 'scope': '限定关键词与页数，非全市场公告完整覆盖',
                       'discovered': 0, 'eligible': 0, 'documents_read': 0, 'verified': 0, 'errors': []}

    def cached_events(self, as_of):
        result=[]
        for row in read_json(self.verified_cache,[]):
            try:
                event=Event.model_validate(row)
                proof=event.verification or {}
                observed=datetime.fromisoformat(proof['observed_at'])
                if (event.verified and proof.get('rule_version')==RULE_VERSION
                        and proof.get('status')=='VERIFIED_RULE' and observed.tzinfo is not None
                        and observed<=as_of and event.event_time<=as_of
                        and event.first_seen_at is not None and event.first_seen_at<=as_of
                        and 0 <= (as_of-event.publish_time).total_seconds() < self.freshness_hours*3600):
                    result.append(event)
            except (KeyError,TypeError,ValueError):
                continue
        return result

    def preserve_verified(self, events):
        # A successful earlier observation survives a later network outage. Its
        # original publication/observation/proof times are retained, never refreshed.
        now=datetime.now(TZ)
        saved={e.event_id:e for e in self.cached_events(now)}
        for event in events:
            if event.verified and (event.verification or {}).get('status')=='VERIFIED_RULE':
                saved[event.event_id]=event
        write_json(self.verified_cache,[e.model_dump(mode='json') for e in saved.values()])

    def discover(self, as_of):
        result = []
        start = as_of.date() - timedelta(days=3)
        for term in self.config.get('search_terms', ['重大合同', '签订合同', '业绩预告']):
            log = {'source_name': 'cninfo_catalyst_discovery', 'operation': term,
                   'fetched_at': datetime.now(TZ).isoformat(), 'success': False, 'count': 0}
            try:
                pages = self.config.get('max_pages_per_term', 2)
                for page in range(1, pages + 1):
                    payload = {'pageNum': str(page), 'pageSize': '30', 'column': 'szse',
                        'tabName': 'fulltext', 'plate': '', 'stock': '', 'searchkey': term,
                        'secid': '', 'category': '', 'trade': '', 'seDate': f'{start}~{as_of.date()}',
                        'sortName': 'time', 'sortType': 'desc', 'isHLtitle': 'false'}
                    data = self.adapter.post('https://www.cninfo.com.cn/new/hisAnnouncement/query', data=payload).json()
                    if not isinstance(data, dict) or 'totalAnnouncement' not in data or 'announcements' not in data:
                        raise ValueError('invalid discovery response')
                    raw = data['announcements'] or []
                    if not isinstance(raw, list): raise ValueError('invalid rows')
                    rows = self.adapter.normalize(raw)
                    if len(rows) != len(raw): self.status['errors'].append('DISCOVERY_ROW_REJECTED')
                    result.extend(rows)
                    log['count'] += len(rows)
                    if not data.get('hasMore') and page * 30 >= int(data['totalAnnouncement']): break
                else:
                    self.status['errors'].append('DISCOVERY_PAGE_BUDGET')
                log['success'] = True
            except Exception as exc:
                log['error'] = type(exc).__name__
                self.status['errors'].append('DISCOVERY_' + type(exc).__name__)
            self.logs.append(log)
            # No repeated requests after an access/rate-limit boundary.
            if log.get('error') == 'HTTPStatusError': break
        # Merge cache to preserve first observations from other announcement collectors.
        if self.adapter.cache_path:
            from src.utils.io import read_json
            cache = read_json(self.adapter.cache_path, {})
            for key, value in self.adapter.first_seen.items():
                cache[key] = min(cache.get(key, value), value)
            write_json(self.adapter.cache_path, cache)
        self.status['discovered'] = len(result)
        return result

    def verify(self, events, as_of):
        eligible = deduplicate(events, as_of)
        self.status['eligible'] = len(eligible)
        verified = []

        for event in sorted(eligible, key=lambda e: e.publish_time, reverse=True):
            if event.verified:
                verified.append(event)
                continue
            if not any(term in event.title for term in ['合同', '订单', '业绩预告']):
                verified.append(event)
                continue
            url = urlparse(event.document_url or '')
            if (url.scheme != 'https' or url.hostname != 'static.cninfo.com.cn'
                    or not url.path.lower().endswith('.pdf') or url.query or url.fragment):
                verified.append(event)
                continue
            if event.event_id in self.attempted:
                verified.append(self.attempted[event.event_id])
                continue
            if self.remaining <= 0:
                self.status['errors'].append('DOCUMENT_BUDGET')
                verified.append(event)
                continue
            self.remaining -= 1
            try:
                # No redirects outside the fixed official host; bounded size and page count.
                with self.adapter.client.stream('GET', event.document_url, follow_redirects=False) as response:
                    if response.status_code != 200: raise ValueError('DOCUMENT_HTTP_' + str(response.status_code))
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 10 * 1024 * 1024: raise ValueError('DOCUMENT_TOO_LARGE')
                if not content.startswith(b'%PDF-'): raise ValueError('NOT_PDF')
                from pypdf import PdfReader
                reader = PdfReader(BytesIO(content))
                if reader.is_encrypted or len(reader.pages) > 40: raise ValueError('DOCUMENT_UNSUPPORTED')
                text = '\n'.join(page.extract_text() or '' for page in reader.pages)
                self.status['documents_read'] += 1
                event = verify_text(event, text, datetime.now(TZ))
            except Exception as exc:
                self.status['errors'].append('DOCUMENT_' + type(exc).__name__)
                event = event.model_copy(update={'verification': {'status': 'UNVERIFIED', 'reason': 'DOCUMENT_READ_FAILED'}})
            self.attempted[event.event_id] = event
            verified.append(event)
        self.status['verified'] = sum(e.verified for e in verified)
        self.status['errors'] = sorted(set(self.status['errors']))
        self.status['status'] = 'PARTIAL' if self.status['errors'] else 'BOUNDED_SCAN_COMPLETE'
        self.preserve_verified(verified)
        return verified
