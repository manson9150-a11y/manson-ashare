from datetime import datetime
import httpx
import pytest

from src.collectors.announcements import CninfoAnnouncementAdapter, AnnouncementAdapter
from src.collectors.base import Collector, Unavailable
from src.catalysts.engine import deduplicate
from src.utils.calendar import TZ


def row(code='600830'):
    return {'secCode': code, 'orgId': 'gssh0600830', 'announcementId': '1225545071',
            'announcementTitle': '<em>香溢融通</em>股票交易异常波动公告',
            'announcementTime': int(datetime(2026, 9, 3, tzinfo=TZ).timestamp()*1000)}


def test_cninfo_normalization_keeps_identity_date_and_unverified_status(config):
    e = CninfoAnnouncementAdapter(config).normalize([row()])[0]
    assert e.stock_code == '600830' and e.title == '香溢融通股票交易异常波动公告'
    assert e.publish_time == datetime(2026, 9, 3, tzinfo=TZ)
    assert e.publish_time_precision == 'date'
    assert e.event_type == '异动公告' and not e.verified and e.impact_score is None
    assert 'announcementId=1225545071' in e.url
    assert e.first_seen_at.tzinfo is not None


def test_date_precision_uses_previous_date_or_prior_observation(config):
    e = CninfoAnnouncementAdapter(config).normalize([row()])[0]
    e.first_seen_at = datetime(2026, 9, 3, 16, 10, tzinfo=TZ)
    assert not deduplicate([e], datetime(2026, 9, 3, 8, 30, tzinfo=TZ))
    assert deduplicate([e], datetime(2026, 9, 3, 21, 30, tzinfo=TZ)) == [e]
    assert deduplicate([e], datetime(2026, 9, 4, 7, 30, tzinfo=TZ)) == [e]
    e.publish_time = e.event_time = datetime(2026, 9, 5, tzinfo=TZ)
    assert not deduplicate([e], datetime(2026, 9, 4, 16, tzinfo=TZ))


def test_cross_source_duplicates_prefer_disclosure_source(config):
    e = CninfoAnnouncementAdapter(config).normalize([row()])[0]
    copy = e.model_copy(update={'source': 'eastmoney_announcements', 'canonical_id': 'em:123', 'reliability': .85})
    assert deduplicate([copy, e], datetime(2026, 9, 4, 16, tzinfo=TZ)) == [e]


@pytest.mark.parametrize('mutation', [{'announcementTime': None}, {'secCode': 'bad'}, {'announcementTitle': ''}])
def test_malformed_record_is_not_a_fake_event(config, mutation):
    assert not CninfoAnnouncementAdapter(config).normalize([{**row(), **mutation}])


def mock_adapter(config, pages, cache_path=None):
    adapter = CninfoAnnouncementAdapter(config, cache_path)
    def handler(request):
        if request.method == 'GET':
            return httpx.Response(200, json={'stockList': [{'code': '600830', 'orgId': 'gssh0600830'}]})
        return httpx.Response(200, json=pages.pop(0))
    adapter.client = httpx.Client(transport=httpx.MockTransport(handler))
    return adapter


def test_complete_pagination_and_first_seen_persistence(config, tmp_path):
    pages = [{'totalAnnouncement': 2, 'announcements': [row()], 'hasMore': True},
             {'totalAnnouncement': 2, 'announcements': [{**row(), 'announcementId': '1225545072'}], 'hasMore': False}]
    path = tmp_path/'seen.json'
    a = mock_adapter(config, pages, path)
    result = a.fetch('events', codes=['600830'])
    assert len(result) == 2 and path.exists()
    next_adapter = CninfoAnnouncementAdapter(config, path)
    assert next_adapter.normalize([row()])[0].first_seen_at == result[0].first_seen_at


@pytest.mark.parametrize('response', [
    {}, {'totalAnnouncement': 1, 'announcements': None},
    {'totalAnnouncement': 1, 'announcements': [row('000001')]},
    {'totalAnnouncement': 1, 'announcements': []},
])
def test_invalid_responses_are_failures_not_empty_success(config, response):
    with pytest.raises(Unavailable):
        mock_adapter(config, [response]).fetch('events', codes=['600830'])


def test_explicit_zero_results_are_valid(config):
    assert mock_adapter(config, [{'totalAnnouncement': 0, 'announcements': None}]).fetch('events', codes=['600830']) == []


def test_truncated_pagination_is_not_complete(config):
    config['announcements']['max_pages_per_stock'] = 1
    with pytest.raises(Unavailable, match='budget'):
        mock_adapter(config, [{'totalAnnouncement': 31, 'announcements': [row()], 'hasMore': True}]).fetch('events', codes=['600830'])


def test_http_failure_records_code_and_switches_source(config):
    primary = CninfoAnnouncementAdapter(config)
    primary.client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    backup = mock_adapter(config, [{'totalAnnouncement': 1, 'announcements': [row()]}])
    backup.source_name = 'test_backup'
    backup.fallback_priority = 1
    collector = Collector([primary, backup])
    assert len(collector.fetch('events', codes=['600830'])) == 1
    assert collector.logs[0]['http_status'] == 403
    assert collector.logs[1]['is_fallback'] and collector.logs[1]['success']


@pytest.mark.parametrize('payload', [{}, {'data': {'list': [], 'total_hits': 5}}])
def test_backup_cannot_call_missing_or_truncated_results_empty(config, payload):
    adapter=AnnouncementAdapter(config)
    adapter.client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=payload)))
    with pytest.raises(Unavailable):
        adapter.fetch('events',codes=['600830'])
