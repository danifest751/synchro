"""Request-local cloud usage totals; no content or credentials are retained."""
from contextlib import contextmanager
from contextvars import ContextVar
import math

_current = ContextVar('cloud_usage', default=None)


@contextmanager
def collect_usage(totals):
    token = _current.set(totals)
    try:
        yield
    finally:
        _current.reset(token)


def record_usage(stage, usage=None):
    totals = _current.get()
    if totals is None:
        return
    entry = totals.setdefault(stage, {'requests': 0, 'reported_cost_usd': 0, 'unpriced_requests': 0})
    entry['requests'] += 1
    cost = usage.get('cost') if isinstance(usage, dict) else None
    if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0:
        entry['reported_cost_usd'] += cost
    else:
        entry['unpriced_requests'] += 1


def usage_summary(totals):
    return {'stages': {stage: dict(value) for stage, value in totals.items()},
            'reported_cost_usd': sum(value['reported_cost_usd'] for value in totals.values()),
            'unpriced_requests': sum(value['unpriced_requests'] for value in totals.values())}
