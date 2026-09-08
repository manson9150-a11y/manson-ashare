from abc import ABC, abstractmethod
from datetime import datetime
import time
import httpx
from tenacity import Retrying, stop_after_attempt, wait_exponential, retry_if_exception
from src.models import SourceLog
from src.utils.calendar import TZ

class Unavailable(RuntimeError):
    pass

class Adapter(ABC):
    source_name = 'base'
    reliability_level = 0.8
    fallback_priority = 0
    def __init__(self, config):
        self.config = config
        self.timestamp = None
        self.client = httpx.Client(timeout=config['sources']['timeout_seconds'], follow_redirects=True, headers={'User-Agent': 'MANSON-Research/0.1', 'Referer': 'https://finance.sina.com.cn/'})
    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)
    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)
    def request(self, method, url, **kwargs):
        for attempt in Retrying(stop=stop_after_attempt(self.config['sources']['attempts']), wait=wait_exponential(multiplier=0.5, max=2), retry=retry_if_exception(lambda e: isinstance(e, httpx.TransportError) or isinstance(e, httpx.HTTPStatusError) and e.response.status_code >= 500), reraise=True):
            with attempt:
                time.sleep(self.config['sources']['request_interval_seconds'])
                response = self.client.request(method, url, **kwargs)
                # 401/403/429 are access/rate boundaries: no bypass and no immediate retry.
                response.raise_for_status()
                self.timestamp = datetime.now(TZ)
                return response
    def health_check(self):
        try:
            return bool(self.fetch('quotes', codes=['600519']))
        except Exception:
            return False
    @abstractmethod
    def fetch(self, operation, **kwargs): ...
    @abstractmethod
    def normalize(self, payload, **kwargs): ...

class Collector:
    def __init__(self, adapters):
        self.adapters = sorted(adapters, key=lambda a: a.fallback_priority)
        self.logs = []
        self.failures = {}
    def fetch(self, operation, accept=None, **kwargs):
        errors = []
        for i, adapter in enumerate(self.adapters):
            key = (adapter.source_name, operation)
            if self.failures.get(key, 0) >= adapter.config['sources']['max_source_failures']:
                continue
            try:
                result = adapter.fetch(operation, **kwargs)
                if result is None or (len(result) == 0 and operation != 'events'):
                    raise Unavailable('empty response')
                if accept is not None:
                    result = accept(result)
                if operation == 'quotes':
                    for q in result:
                        q.fallback = i > 0
                data_time = None
                if operation == 'quotes' and result:
                    data_time = max(q.timestamp for q in result).isoformat()
                elif operation == 'history' and not result.empty:
                    data_time = result.timestamp.max().isoformat()
                elif operation == 'events' and result:
                    data_time = max(e.publish_time for e in result).isoformat()
                self.logs.append(SourceLog(source_name=adapter.source_name, operation=operation, success=True, fetched_at=datetime.now(TZ).isoformat(), timestamp=data_time, reliability_level=adapter.reliability_level, fallback_priority=adapter.fallback_priority, is_fallback=i > 0, count=len(result)).model_dump())
                return result
            except Exception as exc:
                self.failures[key] = self.failures.get(key, 0) + 1
                # Do not persist response bodies, URLs with credentials, or authentication details.
                errors.append(adapter.source_name + ':' + type(exc).__name__)
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                self.logs.append(SourceLog(source_name=adapter.source_name, operation=operation, success=False, fetched_at=datetime.now(TZ).isoformat(), reliability_level=adapter.reliability_level, fallback_priority=adapter.fallback_priority, is_fallback=i > 0, error=type(exc).__name__, http_status=status).model_dump())
        raise Unavailable('; '.join(errors) or 'adapter circuit open')
