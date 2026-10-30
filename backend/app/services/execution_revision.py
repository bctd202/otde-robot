"""Prospective execution repair; existing account policy and positions stay versioned."""
from typing import Any

VERSION = 'decision-clock-v2'


class ExitEvidenceProvider:
    """Separate REST quote health from candle transport health for held exposure."""
    def __init__(self, provider: Any):
        self.provider = provider

    def status(self):
        method = getattr(self.provider, 'option_execution_status', self.provider.status)
        return method()

    def cached_option_chain(self, *args):
        return self.provider.cached_option_chain(*args)
