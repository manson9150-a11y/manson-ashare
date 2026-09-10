"""Anonymous BaoStock daily data in a bounded, isolated SDK process.

The SDK owns a global socket. A separate process prevents concurrent history
requests from sharing sessions and guarantees a hard timeout on a stuck socket.
"""
from datetime import datetime, timedelta
import json
import subprocess
import sys
import threading
import pandas as pd
from .base import Adapter, Unavailable, UnsupportedOperation
from .public import symbol, number
from src.utils.calendar import TZ


class BaoStockAdapter(Adapter):
    source_name = 'baostock'
    fallback_priority = 3

    def __init__(self, config):
        super().__init__(config)
        self._gate = threading.Lock()
        self._offline = False

    def fetch(self, operation, **kwargs):
        if operation not in ('history', 'index_history', 'industry'):
            raise UnsupportedOperation(operation)
        if self._offline:
            raise Unavailable('BaoStock unavailable this run')
        request = {'operation': operation}
        if operation != 'industry':
            sym = symbol(kwargs['code'])
            if sym.startswith('bj'):
                raise UnsupportedOperation('BaoStock Beijing history not enabled')
            bars = kwargs.get('bars', self.config['sources']['history_bars'])
            request.update(code=sym[:2]+'.'+sym[2:], start=str(kwargs['end']-timedelta(days=bars*3)), end=str(kwargs['end']))
        with self._gate:
            if self._offline:
                raise Unavailable('BaoStock unavailable this run')
            try:
                result = subprocess.run([sys.executable, '-m', 'src.collectors.baostock_worker'],
                    input=json.dumps(request), capture_output=True, text=True, timeout=25, check=True)
                payload = json.loads(result.stdout)
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError) as exc:
                self._offline = True
                raise Unavailable('BaoStock worker unavailable') from exc
        if payload.get('error'):
            self._offline = True
            raise Unavailable('BaoStock service unavailable')
        if operation == 'industry':
            return payload['rows']
        rows = []
        for row in payload['rows']:
            if row.get('code') != request['code'] or row.get('adjustflag') != '3':
                raise Unavailable('BaoStock symbol or adjustment mismatch')
            day = row['date']
            if day > request['end']:
                raise Unavailable('BaoStock date exceeds request')
            rows.append({'timestamp': datetime.fromisoformat(day+'T15:00:00').replace(tzinfo=TZ),
                **{key: number(row.get(key)) for key in ('open','high','low','close','volume','amount')},
                'source': self.source_name, 'adjustment': 'none'})
        return pd.DataFrame(rows[-bars:])

    def normalize(self, payload, **kwargs):
        return payload
