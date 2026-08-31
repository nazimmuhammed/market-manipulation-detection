"""
Example plugin detector #2.

Flags a sharp reversal after a sustained directional run - e.g. 4+ ticks
rising followed by a sudden sharp drop. This is a classic "pump, then early
exit" signature that often precedes a full pump-and-dump collapse.
"""
from collections import defaultdict
from app.ml.plugins.base import Detector

_price_history = defaultdict(list)


class MomentumReversalDetector(Detector):
    name = "momentum_reversal"
    description = "Flags a sharp price reversal immediately following a sustained directional run."

    def score(self, ticker, tick, history):
        hist = _price_history[ticker]
        hist.append(tick["close"])
        if len(hist) > 10:
            hist.pop(0)
        if len(hist) < 6:
            return 0.0

        run = hist[-6:-1]
        deltas = [run[i + 1] - run[i] for i in range(len(run) - 1)]
        was_rising = all(d > 0 for d in deltas)
        was_falling = all(d < 0 for d in deltas)

        last_move = hist[-1] - hist[-2]
        run_size = abs(run[-1] - run[0]) or 1e-9
        reversal_size = abs(last_move) / run_size

        if (was_rising and last_move < 0) or (was_falling and last_move > 0):
            return max(0.0, min(100.0, reversal_size * 60))
        return 0.0