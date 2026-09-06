from datetime import date, datetime
from pathlib import Path

import pytest

from src.retrospective import FrozenCollector, RetrospectivePipeline
from src.utils.calendar import TZ
from src.utils.io import write_json
from src.market.engine import market_score

PROJECT = Path(__file__).resolve().parents[1]


def test_retrospective_cannot_write_production(tmp_path):
    for output in [PROJECT, PROJECT / 'data' / 'history']:
        with pytest.raises(ValueError, match='isolated'):
            RetrospectivePipeline(PROJECT, output, date(2026, 9, 4), tmp_path / 'missing.json')


def test_retrospective_does_not_rebuild_intraday_or_present(tmp_path):
    membership = tmp_path / 'membership.json'
    write_json(membership, {'observed_at': '2026-09-06T00:00:00+08:00', 'sectors': []})
    pipeline = RetrospectivePipeline(PROJECT, tmp_path / 'output', date(2026, 9, 4), membership)
    with pytest.raises(ValueError, match='close scan'):
        pipeline.run(date(2026, 9, 4), '1135')
    with pytest.raises(ValueError, match='past'):
        pipeline.run(date(2026, 9, 4), now=datetime(2026, 9, 4, 20, tzinfo=TZ))


def test_frozen_inputs_still_run_acceptance_check(tmp_path):
    class NetworkMustNotRun:
        def fetch(self, *args, **kwargs):
            pytest.fail('Frozen input must be reused')

    write_json(tmp_path / 'universe.json', {'rows': [{'code': '600001'}]})
    collector = FrozenCollector(NetworkMustNotRun(), tmp_path, date(2026, 9, 4))
    def reject(rows):
        raise ValueError('Bad historical input')
    with pytest.raises(ValueError, match='Bad historical input'):
        collector.fetch('universe', accept=reject)


def test_partial_limit_prices_do_not_become_market_total(quote, config):
    known = quote.model_copy(update={'limit_up_price': quote.price, 'limit_down_price': None})
    unknown = quote.model_copy(update={'code': '600002', 'limit_up_price': None, 'limit_down_price': None})
    result = market_score([known, unknown], config, {'status': 'YELLOW'})
    assert result['known_limit_up_count'] == 1
    assert result['limit_up_price_coverage'] == 0.5
    assert result['limit_up_count'] is None
    assert result['limit_down_count'] is None
