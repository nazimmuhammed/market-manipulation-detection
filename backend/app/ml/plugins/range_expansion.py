"""
Example plugin detector #1.

We don't have real bid/ask data, so this uses a well-known proxy: a tick's
intraday high-low range compared to its recent rolling average range. A
sudden, sharp expansion in trading range with no corresponding news is a
classic signature of spoofing / order-book manipulation.
"""
from collections import defaultdict
from app.ml.plugins.base import Detector

_range_history = defaultdict(list)


class RangeExpansionDetector(Detector):
    name = "range_expansion"
    description = "Flags sudden expansion in a tick's high-low range vs its recent rolling average (spread-anomaly proxy)."

    def score(self, ticker, tick, history):
        high = tick.get("high", tick["close"])
        low = tick.get("low", tick["close"])
        rng = max(0.0, high - low)

        hist = _range_history[ticker]
        hist.append(rng)
        if len(hist) > 20:
            hist.pop(0)
        if len(hist) < 6:
            return 0.0

        avg = sum(hist[:-1]) / len(hist[:-1])
        if avg <= 0:
            return 0.0
        expansion = rng / avg
        # 1x = normal, 3x+ = very suspicious
        return max(0.0, min(100.0, (expansion - 1.0) * 40))