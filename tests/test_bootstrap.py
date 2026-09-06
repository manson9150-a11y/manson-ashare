import copy
from datetime import date, datetime
from pathlib import Path

import pytest

from src.bootstrap import load_seed
from src.pipeline import Pipeline
from src.utils.calendar import TZ
from src.utils.io import read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]
DAY = date(2026, 9, 7)


def install_seed(root):
    seed = read_json(PROJECT / 'data/bootstrap/2026-09-07.json')
    write_json(root / 'data/bootstrap/2026-09-07.json', seed)
    return seed


def test_initial_morning_chain_uses_seed_and_retains_provenance(tmp_path, config, monkeypatch):
    seed = install_seed(tmp_path)
    pipeline = Pipeline(PROJECT, tmp_path, 'live', config)
    monkeypatch.delenv('GOOGLE_DOC_ID', raising=False)
    monkeypatch.setattr(pipeline.announcements, 'fetch', lambda *a, **kw: [])
    def no_market_fetch(*a, **kw):
        pytest.fail('Morning initialization must reuse the verified close data')
    monkeypatch.setattr(pipeline.collector, 'fetch', no_market_fetch)
    previous_codes = {s['stock_code'] for g in seed['pools'].values() for s in g}
    for stage, hour, minute, cap in [('0730', 7, 31, 12), ('0830', 8, 31, 10)]:
        run = pipeline.run(DAY, stage, datetime(2026, 9, 7, hour, minute, tzinfo=TZ))
        assert run['status'] == 'COMPLETE', run.get('errors')
        assert run['bootstrap_origin'] == seed['bootstrap_origin']
        assert run['quote_date'] == '2026-09-04'
        codes = {s['stock_code'] for g in run['pools'].values() for s in g}
        assert codes <= previous_codes and len(codes) <= cap and codes
        previous_codes = codes
        assert run['evaluation'] == {}
        assert '初始化' in (tmp_path / f'data/history/2026/09/07/{stage}/report.md').read_text()
    assert not (tmp_path / 'data/history/2026/09/04/2130/stage_results.json').exists()
    assert not (tmp_path / 'data/history/outcomes.json').exists()


@pytest.mark.parametrize('change', ['mode', 'status', 'target', 'quotes', 'created_at'])
def test_invalid_seed_is_not_a_formal_predecessor(tmp_path, config, change):
    seed = copy.deepcopy(install_seed(tmp_path))
    if change in ('mode', 'status'):
        seed[change] = 'COMPLETE' if change == 'status' else 'live'
    elif change == 'target':
        seed['bootstrap_origin']['target_date'] = '2026-09-08'
    elif change == 'quotes':
        seed['quotes'][0]['timestamp'] = '2026-09-07T15:00:00+08:00'
    else:
        seed['bootstrap_origin']['created_at'] = '2026-09-04T21:30:00+08:00'
    write_json(tmp_path / 'data/bootstrap/2026-09-07.json', seed)
    p = Pipeline(PROJECT, tmp_path, 'live', config)
    assert load_seed(tmp_path, DAY, datetime(2026, 9, 7, 7, 31, tzinfo=TZ), p.calendar, config) is None


def test_seed_does_not_bypass_failed_official_predecessor_or_stage_window(tmp_path, config, monkeypatch):
    install_seed(tmp_path)
    p = Pipeline(PROJECT, tmp_path, 'live', config)
    monkeypatch.delenv('GOOGLE_DOC_ID', raising=False)
    write_json(p.stage_path(date(2026, 9, 4), '2130'), {'status': 'DEGRADED'})
    assert p.run(DAY, '0730', datetime(2026, 9, 7, 7, 31, tzinfo=TZ))['status'] == 'MISSING_PREDECESSOR'
    assert p.run(DAY, '0730', datetime(2026, 9, 7, 8, 40, tzinfo=TZ))['status'] == 'OUTSIDE_STAGE_WINDOW'


def test_seed_cannot_be_reused_on_a_later_day(tmp_path, config):
    seed = install_seed(tmp_path)
    write_json(tmp_path / 'data/bootstrap/2026-09-08.json', seed)
    p = Pipeline(PROJECT, tmp_path, 'live', config)
    assert load_seed(tmp_path, date(2026, 9, 8), datetime(2026, 9, 8, 7, 31, tzinfo=TZ), p.calendar, config) is None
